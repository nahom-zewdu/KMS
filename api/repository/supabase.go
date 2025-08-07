package repository

import (
	"context"
	"log"

	"github.com/nahom-zewdu/kMS/api/domain"
	"github.com/supabase-community/supabase-go"
)

type SupabaseClient struct {
	client *supabase.Client
}

func NewSupabaseRepo(url, key string) domain.StoragePort {
	client, err := supabase.NewClient(url, key, nil)
	if err != nil {
		log.Fatalf("Failed to initialize Supabase client: %v", err)
	}

	log.Println("Supabase client initialized successfully")
	return &SupabaseClient{client: client}
}

func (sc *SupabaseClient) Insert(ctx context.Context, table string, data map[string]interface{}) error {
	_, _, err := sc.client.From(table).Insert(data, false, "", "", "").Execute()
	if err != nil {
		log.Printf("Error inserting data into table %s: %v", table, err)
		return err
	}

	return nil
}
