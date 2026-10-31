package services

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"time"
)

func VerifySlackRequest(r *http.Request, body []byte) bool {
	secret := os.Getenv("SLACK_SIGNING_SECRET")
	timestamp := r.Header.Get("X-Slack-Request-Timestamp")
	signature := r.Header.Get("X-Slack-Signature")

	if secret == "" || timestamp == "" || signature == "" {
		return false
	}

	ts, err := strconv.ParseInt(timestamp, 10, 64)
	if err != nil {
		return false
	}
	delta := time.Since(time.Unix(ts, 0))
	if delta < -5*time.Minute || delta > 5*time.Minute {
		return false
	}

	basestring := fmt.Sprintf("v0:%s:%s", timestamp, string(body))
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(basestring))
	expectedSig := "v0=" + hex.EncodeToString(mac.Sum(nil))

	return hmac.Equal([]byte(expectedSig), []byte(signature))
}
