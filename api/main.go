// main.go
package main

import (
	"log"
	"os"

	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"
	"github.com/nahom-zewdu/kMS/api/handlers"
	"github.com/nahom-zewdu/kMS/api/repository"
	"github.com/nahom-zewdu/kMS/api/services"
)

func main() {
	r := gin.Default()

	// Load environment variables from .env file
	if err := godotenv.Load(); err != nil {
		log.Println("No .env file found, proceeding with defaults")
	}

	supabase_url := os.Getenv("SUPABASE_URL")
	supabase_key := os.Getenv("SUPABASE_KEY")

	upstash_url := os.Getenv("UPSTASH_REDIS_REST_URL")
	upstash_token := os.Getenv("UPSTASH_REDIS_REST_TOKEN")

	slackBotToken := os.Getenv("SLACK_BOT_TOKEN")
	slackSigningKey := os.Getenv("SLACK_SIGNING_SECRET")

	// Initialize storage and publisher
	storage := repository.NewSupabaseRepo(supabase_url, supabase_key)
	publisher := repository.NewRedisStream(upstash_url, upstash_token)

	// Initialize repositories and services
	queryRepo := repository.NewQueryRepository(publisher, storage)
	queryService := services.NewQueryService(queryRepo)

	slackRepo := repository.NewSlackRepo(storage)
	slackService := services.NewSlackService(slackRepo, publisher)
	slackBotService := services.NewSlackBot(slackBotToken, slackSigningKey, queryService)

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
