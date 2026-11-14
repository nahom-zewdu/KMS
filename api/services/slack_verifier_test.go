package services

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestVerifySlackRequestRejectsInvalidAndOutOfWindowSignatures(t *testing.T) {
	t.Setenv("SLACK_SIGNING_SECRET", "test-secret")
	body := []byte(`{"type":"url_verification"}`)
	for _, test := range []struct {
		name string
		when time.Time
		want bool
	}{
		{name: "current valid", when: time.Now(), want: true},
		{name: "invalid signature", when: time.Now(), want: false},
		{name: "too old", when: time.Now().Add(-6 * time.Minute), want: false},
		{name: "too far in future", when: time.Now().Add(6 * time.Minute), want: false},
	} {
		t.Run(test.name, func(t *testing.T) {
			timestamp := fmt.Sprintf("%d", test.when.Unix())
			request := httptest.NewRequest("POST", "/slack/events", nil)
			request.Header.Set("X-Slack-Request-Timestamp", timestamp)
			signature := slackRequestSignature("test-secret", timestamp, body)
			if test.name == "invalid signature" {
				signature = "v0=" + strings.Repeat("0", 64)
			}
			request.Header.Set("X-Slack-Signature", signature)
			if got := VerifySlackRequest(request, body); got != test.want {
				t.Fatalf("VerifySlackRequest() = %v, want %v", got, test.want)
			}
		})
	}
}

func slackRequestSignature(secret, timestamp string, body []byte) string {
	mac := hmac.New(sha256.New, []byte(secret))
	_, _ = fmt.Fprintf(mac, "v0:%s:%s", timestamp, body)
	return "v0=" + hex.EncodeToString(mac.Sum(nil))
}
