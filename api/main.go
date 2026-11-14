// main.go
package main

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/joho/godotenv"
	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/nahom-zewdu/kMS/api/handlers"
	"github.com/nahom-zewdu/kMS/api/repository"
	"github.com/nahom-zewdu/kMS/api/services"
	"github.com/redis/go-redis/v9"
)

// main initializes and starts the KnowSphere backend server.
func main() {
	if err := run(); err != nil {
		log.Fatal(err)
	}
}

func run() error {
	// Load environment variables
	if err := godotenv.Load(); err != nil {
		log.Println("No .env file found, proceeding with defaults")
	}

	supabaseURL := os.Getenv("SUPABASE_URL")
	supabaseKey := os.Getenv("SUPABASE_KEY")
	redisAddr := os.Getenv("REDIS_ADDR")
	redisPassword := os.Getenv("REDIS_PASSWORD")
	slackBotToken := os.Getenv("SLACK_BOT_TOKEN")
	slackSignKey := os.Getenv("SLACK_SIGNING_SECRET")
	githubSecret := os.Getenv("GITHUB_WEBHOOK_SECRET")
	port := os.Getenv("PORT")

	if port == "" {
		port = "8080"
	}

	// Validate environment variables
	if supabaseURL == "" || supabaseKey == "" || redisAddr == "" || slackBotToken == "" || slackSignKey == "" || githubSecret == "" {
		return fmt.Errorf("missing required environment variables: SUPABASE_URL=%v, SUPABASE_KEY=%v, REDIS_ADDR=%v, SLACK_BOT_TOKEN=%v, SLACK_SIGNING_SECRET=%v, GITHUB_WEBHOOK_SECRET=%v",
			supabaseURL != "", supabaseKey != "", redisAddr != "", slackBotToken != "", slackSignKey != "", githubSecret != "")
	}

	// Initialize Supabase client
	supabaseRepo := repository.NewSupabaseRepo(supabaseURL, supabaseKey)

	// Initialize Redis client (Upstash)
	redisClient := redis.NewClient(&redis.Options{
		Addr:      redisAddr,
		Password:  redisPassword,
		DB:        0,
		TLSConfig: &tls.Config{MinVersion: tls.VersionTLS12}, // Enable TLS for Upstash
	})
	ctx, cancelPing := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancelPing()
	if err := redisClient.Ping(ctx).Err(); err != nil {
		if closeErr := redisClient.Close(); closeErr != nil {
			log.Printf("Failed to close Redis client after failed startup: %v", closeErr)
		}
		return fmt.Errorf("failed to connect to Redis at %s: %w", redisAddr, err)
	}
	defer func() {
		if err := redisClient.Close(); err != nil {
			log.Printf("Failed to close Redis client: %v", err)
		}
	}()
	log.Printf("Successfully connected to Redis at %s", redisAddr)
	redisStream := repository.NewRedisStream(redisClient)
	outboxRepository, ok := supabaseRepo.(domain.IngestionOutboxRepository)
	if !ok {
		return fmt.Errorf("Supabase repository does not support transactional ingestion outbox")
	}
	outboxDispatcher := services.NewIngestionOutboxDispatcher(outboxRepository, redisStream)

	// Initialize services
	coreIngestService := services.NewCoreIngest(supabaseRepo, redisStream)
	slackIngestService := services.NewSlackIngest(coreIngestService)
	githubIngestService := services.NewGitHubIngest(coreIngestService)
	playbookService := services.NewPlaybookService()
	slackBotService := services.NewSlackBot(slackBotToken, coreIngestService, redisStream, playbookService)
	codebaseService := services.NewCodebaseService(redisStream)

	// Setup routes
	router := handlers.SetupRoutes(slackIngestService, slackBotService, githubIngestService, slackBotToken, slackSignKey, githubSecret, codebaseService, redisStream, supabaseRepo)

	server := newHTTPServer(":"+port, router)
	listener, err := net.Listen("tcp", server.Addr)
	if err != nil {
		return fmt.Errorf("failed to listen on %s: %w", server.Addr, err)
	}
	shutdownContext, stopSignals := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stopSignals()
	dispatcherContext, cancelDispatcher := context.WithCancel(shutdownContext)
	defer cancelDispatcher()
	dispatcherDone := make(chan struct{})
	go func() {
		defer close(dispatcherDone)
		outboxDispatcher.Run(dispatcherContext)
	}()
	log.Printf("kms backend server is listening on port %s", port)
	serverErr := serveHTTP(server, listener, shutdownContext)
	cancelDispatcher()
	<-dispatcherDone
	return serverErr
}

func serveHTTP(server *http.Server, listener net.Listener, shutdownContext context.Context) error {
	serverErrors := make(chan error, 1)
	go func() {
		serverErrors <- server.Serve(listener)
	}()

	select {
	case err := <-serverErrors:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return fmt.Errorf("HTTP server failed: %w", err)
	case <-shutdownContext.Done():
		log.Printf("Shutdown signal received; draining HTTP server")
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		if err := server.Shutdown(ctx); err != nil {
			log.Printf("Graceful shutdown failed: %v; forcing server close", err)
			if closeErr := server.Close(); closeErr != nil {
				return fmt.Errorf("HTTP shutdown failed (%v), force close failed: %w", err, closeErr)
			}
			return fmt.Errorf("HTTP graceful shutdown timed out: %w", err)
		}
		if err := <-serverErrors; err != nil && !errors.Is(err, http.ErrServerClosed) {
			return fmt.Errorf("HTTP server stopped unexpectedly: %w", err)
		}
	}
	return nil
}

func newHTTPServer(addr string, handler http.Handler) *http.Server {
	return &http.Server{
		Addr:              addr,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      90 * time.Second,
		IdleTimeout:       120 * time.Second,
		MaxHeaderBytes:    1 << 20,
	}
}
