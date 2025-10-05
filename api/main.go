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
	upstashURL := os.Getenv("UPSTASH_REDIS_REST_URL")
	upstashToken := os.Getenv("UPSTASH_REDIS_REST_TOKEN")
	slackBotToken := os.Getenv("SLACK_BOT_TOKEN")
	slackSigningKey := os.Getenv("SLACK_SIGNING_SECRET")

	// Initialize storage and publisher
	storage := repository.NewSupabaseRepo(supabaseURL, supabaseKey)
	publisher := repository.NewRedisStream(upstashURL, upstashToken)

	// Initialize Redis for Pub/Sub
	redisClient := redis.NewClient(&redis.Options{
		Addr:     upstashURL,
		Password: upstashToken,
		DB:       0,
	})
	if err := redisClient.Ping(context.Background()).Err(); err != nil {
		log.Fatalf("Failed to initialize Redis client: %v", err)
	}

	// Initialize repositories and services
	slackRepo := repository.NewSlackRepo(storage)
	queryRepo := repository.NewQueryRepository(publisher, storage)
	slackService := services.NewSlackService(slackRepo, publisher)
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
