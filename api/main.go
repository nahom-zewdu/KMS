// main.go
package main

import (
	"context"
	"log"
	"os"

	"github.com/joho/godotenv"
	"github.com/nahom-zewdu/kMS/api/handlers"
	"github.com/nahom-zewdu/kMS/api/repository"
	"github.com/nahom-zewdu/kMS/api/services"
	"github.com/redis/go-redis/v9"
)

// main initializes and starts the KnowSphere backend.
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
		log.Fatal("Missing required environment variables")
	}

	// Initialize Supabase client
	supabaseRepo := repository.NewSupabaseRepo(supabaseURL, supabaseKey)

	// Initialize Redis client (Upstash)
	redisClient := redis.NewClient(&redis.Options{
		Addr:     redisAddr,
		Password: redisPassword,
		DB:       0,
	})
	if err := redisClient.Ping(context.Background()).Err(); err != nil {
		log.Fatalf("Failed to connect to Redis: %v", err)
	}
	redisStream := repository.NewRedisStream(redisClient)

	// Initialize services
	coreIngestService := services.NewCoreIngest(supabaseRepo, redisStream)
	slackIngestService := services.NewSlackIngest(coreIngestService)
	githubIngestService := services.NewGitHubIngest(coreIngestService)
	slackBotService := services.NewSlackBot(slackBotToken, coreIngestService, redisStream)

	// Setup routes
	router := handlers.SetupRoutes(slackIngestService, slackBotService, githubIngestService, slackBotToken, slackSignKey, githubSecret)

	// Start server
	log.Printf("Starting server on port %s", port)
	if err := router.Run(":" + port); err != nil {
		log.Fatalf("Server failed to start: %v", err)
	}
}
