package llm

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"unicode/utf8"

	"github.com/tengteng/go-code-analyzer/internal/analyzer"
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
func (c *OpenAIClient) GetCompletion(systemPrompt string, prompt string) (string, error) {
	// Create request body
	reqBody := openAIRequest{
		Model: c.Model,
		Messages: []message{
			{
				Role:    "system",
				Content: systemPrompt,
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
	case "gpt-4.1-mini":
		maxTokens = 16384
	default:
		maxTokens = 4096 // Default conservative limit
	}

	// Add buffer for system message and response
	estimatedTotal := estimatedTokens + 150

	return estimatedTotal, estimatedTotal <= maxTokens
}

// TagFunctions takes a batch of FunctionNodes and generate tags for them
// Returns a map with node IDs as keys and tags as values
func (c *OpenAIClient) TagFunctions(batch []analyzer.WeightedNode) map[string][]string {
	result := make(map[string][]string)

	// Prepare function information for the prompt
	type FunctionInfo struct {
		PackageAndFunctionName string `json:"package_and_function_name"`
		FunctionDefinition     string `json:"function_definition"`
	}

	var functions []FunctionInfo

	for _, node := range batch {
		if node.Type != analyzer.FunctionNode {
			continue
		}
		funcData, ok := node.GraphNode.Data.(map[string]interface{})
		if !ok {
			continue
		}

		funcName, ok := funcData["function_name"].(string)
		if !ok {
			continue
		}

		packageName, ok := funcData["package_name"].(string)
		if !ok {
			continue
		}
		inputParams, ok := funcData["input_params"].(string)
		if !ok {
			continue
		}
		returnParams, ok := funcData["return_params"].(string)
		if !ok {
			continue
		}
		funcDefinition := fmt.Sprintf("func %s(%s) %s", funcName, inputParams, returnParams)

		functions = append(functions, FunctionInfo{
			PackageAndFunctionName: packageName + "." + funcName,
			FunctionDefinition:     funcDefinition,
		})
	}

	if len(functions) == 0 {
		return result
	}

	// Format function information as JSON for the prompt
	functionsJSON, err := json.Marshal(functions)
	if err != nil {
		fmt.Println("Error marshalling functions:", err)
		return result
	}

	systemPrompt := "You are analyzing a Go codebase to tag functions based on their likely purpose or domain."
	// Create the prompt
	prompt := fmt.Sprintf(`
For each of the following functions, provide 1-3 tags that best describe the function's purpose:
%s

Your response should be a JSON object with function IDs as keys and arrays of tags as values:
{
  "package_and_function_name_1": ["Tag1", "Tag2"],
  "package_and_function_name_2": ["Tag3"]
}

If you believe a function is relevant to the core / main line logic of the repository, add a "core" in the result tags.
If you believe a function is relevant to a branch line logic of the repository, add a "branch" in the result tags.
If you believe a function is for utility / helper / testing / logging / etc, add a "utility" in the result tags.
Entry functions should never be tagged with "utility". Any function should be tagged with at least one tag.
`, string(functionsJSON))

	// Check if the prompt is too long
	_, isWithinTokenLimit := c.CheckTokenCount(prompt)
	if !isWithinTokenLimit {
		fmt.Println("Prompt is too long, skipping...")
		return result
	}
	fmt.Printf("Prompt: %s\n", prompt)

	// Get completion from OpenAI
	jsonResponse, err := c.GetCompletion(systemPrompt, prompt)
	if err != nil {
		fmt.Println("Error getting completion:", err)
		return result
	}

	fmt.Printf("JSON response: %s\n", jsonResponse)

	// Parse the response
	var tagsMap map[string][]string
	err = json.Unmarshal([]byte(jsonResponse), &tagsMap)
	if err != nil {
		fmt.Println("Error unmarshalling response:", err)
		return result
	}

	for funcName, tags := range tagsMap {
		result[funcName] = tags
	}

	return result
}
