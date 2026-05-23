// main.go
package main

import (
	"context"
	"crypto/tls"
	"log"
	"os"

	"github.com/joho/godotenv"
	"github.com/nahom-zewdu/kMS/api/handlers"
	"github.com/nahom-zewdu/kMS/api/repository"
	"github.com/nahom-zewdu/kMS/api/services"
	"github.com/redis/go-redis/v9"
)

// main initializes and starts the KnowSphere backend server.
func main() {
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
		log.Fatalf("Missing required environment variables: SUPABASE_URL=%v, SUPABASE_KEY=%v, REDIS_ADDR=%v, SLACK_BOT_TOKEN=%v, SLACK_SIGNING_SECRET=%v, GITHUB_WEBHOOK_SECRET=%v",
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
	defer redisClient.Close()
	ctx := context.Background()
	if err := redisClient.Ping(ctx).Err(); err != nil {
		log.Fatalf("Failed to connect to Redis at %s: %v", redisAddr, err)
	}
	log.Printf("Successfully connected to Redis at %s", redisAddr)
	redisStream := repository.NewRedisStream(redisClient)

	// Initialize services
	coreIngestService := services.NewCoreIngest(supabaseRepo, redisStream)
	slackIngestService := services.NewSlackIngest(coreIngestService)
	githubIngestService := services.NewGitHubIngest(coreIngestService)
	playbookService := services.NewPlaybookService()
	slackBotService := services.NewSlackBot(slackBotToken, coreIngestService, redisStream, playbookService)

	// Setup routes
	router := handlers.SetupRoutes(slackIngestService, slackBotService, githubIngestService, slackBotToken, slackSignKey, githubSecret)

	// Start server
	log.Printf("Starting server on port %s", port)
	if err := router.Run(":" + port); err != nil {
		log.Fatalf("Server failed to start: %v", err)
	}
}
