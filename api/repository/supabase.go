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
	return &SupabaseClient{client: client}
}

func (sc *SupabaseClient) Insert(ctx context.Context, table string, data map[string]interface{}) error {
	_, _, err := sc.client.From(table).Insert(data, false, "", "", "").Execute()
	return err
}
