package services

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/nahom-zewdu/kMS/api/domain"
)

type slackBotRedis struct {
	mu              sync.Mutex
	subscribed      bool
	published       bool
	publishedJob    domain.JobPayload
	answer          chan string
	subscriptionCtx context.Context
	cleanup         chan struct{}
	publishErr      error
	subscribeErr    error
	onPublish       func(chan string)
}

func newSlackBotRedis() *slackBotRedis {
	return &slackBotRedis{
		answer:  make(chan string, 1),
		cleanup: make(chan struct{}),
	}
}

func (r *slackBotRedis) Publish(_ context.Context, _ string, payload domain.JobPayload) error {
	r.mu.Lock()
	r.published = true
	r.publishedJob = payload
	subscribed := r.subscribed
	publishErr := r.publishErr
	onPublish := r.onPublish
	r.mu.Unlock()
	if !subscribed {
		return errors.New("query was published before subscription")
	}
	if publishErr != nil {
		return publishErr
	}
	if onPublish != nil {
		onPublish(r.answer)
	}
	return nil
}

func (r *slackBotRedis) Subscribe(ctx context.Context, _ string) (<-chan string, error) {
	r.mu.Lock()
	r.subscribed = true
	r.subscriptionCtx = ctx
	subscribeErr := r.subscribeErr
	r.mu.Unlock()
	if subscribeErr != nil {
		return nil, subscribeErr
	}
	go func() {
		<-ctx.Done()
		close(r.cleanup)
	}()
	return r.answer, nil
}

func (*slackBotRedis) CacheGet(context.Context, string) (string, error) {
	return "", nil
}

func (*slackBotRedis) CacheSet(context.Context, string, string, time.Duration) error {
	return nil
}

func (r *slackBotRedis) waitForCleanup(t *testing.T) {
	t.Helper()
	select {
	case <-r.cleanup:
	case <-time.After(time.Second):
		t.Fatal("subscription context was not canceled")
	}
}

func TestSlackBotRequestAnswer(t *testing.T) {
	tests := []struct {
		name       string
		configure  func(*slackBotRedis, context.CancelFunc)
		timeout    time.Duration
		wantAnswer string
		wantErr    string
	}{
		{
			name: "immediate worker response",
			configure: func(redis *slackBotRedis, _ context.CancelFunc) {
				redis.onPublish = func(answer chan string) { answer <- "ready" }
			},
			timeout:    time.Second,
			wantAnswer: "ready",
		},
		{
			name: "delayed worker response",
			configure: func(redis *slackBotRedis, _ context.CancelFunc) {
				redis.onPublish = func(answer chan string) {
					go func() {
						time.Sleep(10 * time.Millisecond)
						answer <- "later"
					}()
				}
			},
			timeout:    time.Second,
			wantAnswer: "later",
		},
		{
			name: "worker result channel closes",
			configure: func(redis *slackBotRedis, _ context.CancelFunc) {
				redis.onPublish = func(answer chan string) { close(answer) }
			},
			timeout: time.Second,
			wantErr: "subscription closed",
		},
		{
			name: "publish failure",
			configure: func(redis *slackBotRedis, _ context.CancelFunc) {
				redis.publishErr = errors.New("redis unavailable")
			},
			timeout: time.Second,
			wantErr: "redis unavailable",
		},
		{
			name: "context cancellation",
			configure: func(redis *slackBotRedis, cancel context.CancelFunc) {
				redis.onPublish = func(chan string) { cancel() }
			},
			timeout: time.Second,
			wantErr: "context canceled",
		},
		{
			name:      "query timeout",
			configure: func(*slackBotRedis, context.CancelFunc) {},
			timeout:   15 * time.Millisecond,
			wantErr:   "deadline exceeded",
		},
		{
			name:      "worker failure without a result",
			configure: func(*slackBotRedis, context.CancelFunc) {},
			timeout:   15 * time.Millisecond,
			wantErr:   "deadline exceeded",
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			parent, cancel := context.WithCancel(context.Background())
			defer cancel()
			redis := newSlackBotRedis()
			test.configure(redis, cancel)

			answer, err := (&SlackBot{redis: redis}).requestAnswer(
				parent, "query-id", "question", "company-a", test.timeout,
			)

			if test.wantErr == "" {
				if err != nil {
					t.Fatalf("requestAnswer() error = %v", err)
				}
				if answer != test.wantAnswer {
					t.Fatalf("requestAnswer() = %q, want %q", answer, test.wantAnswer)
				}
			} else if err == nil || !strings.Contains(err.Error(), test.wantErr) {
				t.Fatalf("requestAnswer() error = %v, want substring %q", err, test.wantErr)
			}

			redis.waitForCleanup(t)
			redis.mu.Lock()
			defer redis.mu.Unlock()
			if !redis.subscribed {
				t.Fatal("result subscription was not established")
			}
			if redis.publishErr == nil && !redis.published {
				t.Fatal("query job was not published")
			}
			if redis.publishedJob.CompanyID != "company-a" {
				t.Fatalf("published company_id = %q, want company-a", redis.publishedJob.CompanyID)
			}
		})
	}
}

func TestSlackBotRequestAnswerSubscribeFailureDoesNotPublish(t *testing.T) {
	redis := newSlackBotRedis()
	redis.subscribeErr = errors.New("subscription unavailable")

	_, err := (&SlackBot{redis: redis}).requestAnswer(
		context.Background(), "query-id", "question", "company-a", time.Second,
	)
	if err == nil || !strings.Contains(err.Error(), "subscription unavailable") {
		t.Fatalf("requestAnswer() error = %v, want subscription failure", err)
	}
	if redis.published {
		t.Fatal("query job was published without an active result subscription")
	}
}
