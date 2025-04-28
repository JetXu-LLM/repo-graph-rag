package llm

// LLMClient defines the interface for interacting with an LLM service
type LLMClient interface {
	// GetCompletion sends a prompt to the LLM and returns the response
	GetCompletion(systemPrompt string, prompt string) (string, error)
}
