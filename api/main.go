package main

import (
	"context"
	"log"
	"os"

	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"
	"github.com/nahom-zewdu/kMS/api/handlers"
	"github.com/nahom-zewdu/kMS/api/repository"
	"github.com/nahom-zewdu/kMS/api/services"
	"github.com/redis/go-redis/v9"
)

func main() {
	r := gin.Default()

	if err := godotenv.Load(); err != nil {
		log.Println("No .env file found, proceeding with defaults")
	}

	supabaseURL := os.Getenv("SUPABASE_URL")
	supabaseKey := os.Getenv("SUPABASE_KEY")

	upstashRestURL := os.Getenv("UPSTASH_REDIS_REST_URL")
	upstashRestToken := os.Getenv("UPSTASH_REDIS_REST_TOKEN")
	upstashRedisURL := os.Getenv("UPSTASH_REDIS_URL")
	// upstashRedisToken := os.Getenv("UPSTASH_REDIS_TOKEN")

	slackBotToken := os.Getenv("SLACK_BOT_TOKEN")
	slackSigningKey := os.Getenv("SLACK_SIGNING_SECRET")

	// Initialize storage and publisher
	storage := repository.NewSupabaseRepo(supabaseURL, supabaseKey)
	publisher := repository.NewRedisStream(upstashRestURL, upstashRestToken)

	// Initialize Redis for Pub/Sub
	opt, err := redis.ParseURL(upstashRedisURL)
	if err != nil {
		log.Fatalf("Failed to parse Redis URL: %v", err)
	}
	// opt.Password = upstashRedisToken // Set the password from the environment variable

	redisClient := redis.NewClient(opt)
	if err := redisClient.Ping(context.Background()).Err(); err != nil {
		log.Fatalf("Failed to initialize Redis client: %v", err)
	}

	// Initialize repositories and services
	slackRepo := repository.NewIngestRepository(storage)
	queryRepo := repository.NewQueryRepository(publisher, storage)
	slackService := services.NewIngestService(slackRepo, publisher)
	queryService := services.NewQueryService(queryRepo)
	slackBotService := services.NewSlackBot(slackBotToken, slackSigningKey, slackService, redisClient)

	// Setup routes
	handlers.SetupRoutes(r, slackService, queryService, slackBotService, slackSigningKey)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting server on port %s\n", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("Server failed to start: %v", err)
	}
}
