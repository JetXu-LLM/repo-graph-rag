package llm

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"unicode/utf8"
)

// OpenAIClient implements LLMClient for OpenAI API
type OpenAIClient struct {
	APIKey  string
	Model   string
	BaseURL string
}

// NewOpenAIClient creates a new OpenAI client
func NewOpenAIClient(apiKey string, model string) *OpenAIClient {
	return &OpenAIClient{
		APIKey:  apiKey,
		Model:   model,
		BaseURL: "https://api.openai.com/v1/chat/completions",
	}
}

// Request structure for OpenAI API
type openAIRequest struct {
	Model    string    `json:"model"`
	Messages []message `json:"messages"`
}

type message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// Response structure from OpenAI API
type openAIResponse struct {
	Choices []struct {
		Message struct {
			Content string `json:"content"`
		} `json:"message"`
	} `json:"choices"`
	Error *struct {
		Message string `json:"message"`
	} `json:"error,omitempty"`
}

// GetCompletion implements the LLMClient interface
func (c *OpenAIClient) GetCompletion(prompt string) (string, error) {
	// Create request body
	reqBody := openAIRequest{
		Model: c.Model,
		Messages: []message{
			{
				Role:    "system",
				Content: "You are a helpful assistant specialized in analyzing Go code importance.",
			},
			{
				Role:    "user",
				Content: prompt,
			},
		},
	}

	// Convert request to JSON
	jsonData, err := json.Marshal(reqBody)
	if err != nil {
		return "", fmt.Errorf("error marshaling request: %v", err)
	}

	// Create HTTP request
	req, err := http.NewRequest("POST", c.BaseURL, bytes.NewBuffer(jsonData))
	if err != nil {
		return "", fmt.Errorf("error creating request: %v", err)
	}

	// Set headers
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+c.APIKey)

	// Send request
	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("error sending request: %v", err)
	}
	defer resp.Body.Close()

	// Read response
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("error reading response: %v", err)
	}

	// Parse response
	var openAIResp openAIResponse
	if err := json.Unmarshal(body, &openAIResp); err != nil {
		return "", fmt.Errorf("error unmarshaling response: %v", err)
	}

	// Check for API error
	if openAIResp.Error != nil {
		return "", fmt.Errorf("API error: %s", openAIResp.Error.Message)
	}

	// Check if we have choices
	if len(openAIResp.Choices) == 0 {
		return "", fmt.Errorf("no completion choices returned")
	}

	// Extract JSON part from the response
	content := openAIResp.Choices[0].Message.Content
	content = extractJSON(content)

	return content, nil
}

// extractJSON attempts to extract a JSON object from text that might contain markdown or explanations
func extractJSON(text string) string {
	// Check if content is wrapped in ```json ... ```
	if strings.Contains(text, "```json") {
		parts := strings.Split(text, "```json")
		if len(parts) > 1 {
			jsonPart := strings.Split(parts[1], "```")[0]
			return strings.TrimSpace(jsonPart)
		}
	}

	// Check if content is wrapped in ``` ... ```
	if strings.Contains(text, "```") {
		parts := strings.Split(text, "```")
		if len(parts) > 1 {
			jsonPart := parts[1]
			return strings.TrimSpace(jsonPart)
		}
	}

	// If we can't find code blocks, try to find JSON object delimiters
	if strings.Contains(text, "{") && strings.Contains(text, "}") {
		start := strings.Index(text, "{")
		end := strings.LastIndex(text, "}")
		if start < end {
			return text[start : end+1]
		}
	}

	// If all else fails, return the original text
	return text
}

// Simplified token count estimation
// A more accurate implementation would use tiktoken or a similar tokenizer
func estimateTokenCount(text string) int {
	// As a rough estimate, 1 token ~= 4 characters for English text
	return utf8.RuneCountInString(text) / 4
}

// CheckTokenCount checks if a prompt would exceed token limits
func (c *OpenAIClient) CheckTokenCount(prompt string) (int, bool) {
	// Estimate token count
	estimatedTokens := estimateTokenCount(prompt)

	// Different models have different token limits
	var maxTokens int
	switch c.Model {
	case "gpt-4":
		maxTokens = 8192
	case "gpt-4-32k":
		maxTokens = 32768
	case "gpt-3.5-turbo":
		maxTokens = 4096
	case "gpt-3.5-turbo-16k":
		maxTokens = 16384
	default:
		maxTokens = 4096 // Default conservative limit
	}

	// Add buffer for system message and response
	estimatedTotal := estimatedTokens + 150

	return estimatedTotal, estimatedTotal <= maxTokens
}
