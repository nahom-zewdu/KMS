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

	url := os.Getenv("SUPABASE_URL")
	key := os.Getenv("SUPABASE_KEY")

	storage := repository.NewSupabaseRepo(url, key)
	repo := repository.NewSlackRepo(storage)
	service := services.NewSlackService(repo)
	handlers.SetupRoutes(r, service)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	log.Printf("Starting server on port %s\n", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("Server failed to start: %v", err)
	}
}
