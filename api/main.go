package main

import (
	"context"
	"crypto/tls"
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
	upstashRedisURL := os.Getenv("UPSTASH_REDIS_URL") // e.g., sought-perch-5675.upstash.io:6379
	upstashRedisToken := os.Getenv("UPSTASH_REDIS_TOKEN")
	slackBotToken := os.Getenv("SLACK_BOT_TOKEN")
	slackSigningKey := os.Getenv("SLACK_SIGNING_SECRET")

	// Initialize storage
	storage := repository.NewSupabaseRepo(supabaseURL, supabaseKey)

	// Initialize Redis for Streams, Pub/Sub, caching
	redisClient := redis.NewClient(&redis.Options{
		Addr:      upstashRedisURL,
		Password:  upstashRedisToken,
		DB:        0,
		TLSConfig: &tls.Config{InsecureSkipVerify: true}, // Upstash requires TLS
	})
	if err := redisClient.Ping(context.Background()).Err(); err != nil {
		log.Fatalf("Failed to initialize Redis client: %v", err)
	}

	// Initialize RedisStream
	redisStream := repository.NewRedisStream(redisClient)

	// Initialize repositories and services
	ingestRepo := repository.NewIngestRepository(storage)
	queryRepo := repository.NewQueryRepository(redisStream, storage) // Use redisStream
	ingestService := services.NewIngestService(ingestRepo, redisClient)
	queryService := services.NewQueryService(queryRepo)
	slackBotService := services.NewSlackBot(slackBotToken, slackSigningKey, ingestService, redisClient)

	// Setup routes
	handlers.SetupRoutes(r, ingestService, queryService, slackBotService, slackSigningKey)

	port := os.Getenv("PORT")
	if port == "" {
		port = "9090"
	}

	log.Printf("Starting server on port %s\n", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("Server failed to start: %v", err)
	}
}
