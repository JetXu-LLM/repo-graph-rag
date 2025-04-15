package main

import (
	"flag"
	"fmt"
	"log"
	"os"

	"github.com/tengteng/go-code-analyzer/internal/llm"
)

func main() {
	// Define flags
	enrichedGraphPath := flag.String("graph", "enriched_kg.json", "Path to the enriched knowledge graph file")
	apiKey := flag.String("apikey", "", "OpenAI API key")
	model := flag.String("model", "gpt-4", "Model to use for LLM analysis")
	packageBatchSize := flag.Int("pkg-batch", 10, "Batch size for package analysis")
	structBatchSize := flag.Int("struct-batch", 10, "Batch size for struct analysis")
	funcBatchSize := flag.Int("func-batch", 10, "Batch size for function analysis")
	debug := flag.Bool("debug", false, "Debug mode")

	flag.Parse()

	// Check if API key is provided
	if *apiKey == "" {
		// Try to get API key from environment
		*apiKey = os.Getenv("OPENAI_API_KEY")
		if *apiKey == "" {
			log.Fatal("OpenAI API key not provided. Use -apikey flag or set OPENAI_API_KEY environment variable.")
		}
	}

	// Create LLM client
	llmClient := llm.NewOpenAIClient(*apiKey, *model)

	// Create importance analyzer with batch sizes
	analyzer, err := llm.NewImportanceAnalyzerWithBatchSizes(
		llmClient,
		*enrichedGraphPath,
		*packageBatchSize,
		*structBatchSize,
		*funcBatchSize,
	)
	if err != nil {
		log.Fatalf("Error creating importance analyzer: %v", err)
	}

	// Analyze importance
	fmt.Println("Starting hierarchical importance analysis...")
	if err := analyzer.AnalyzeImportance(*debug); err != nil {
		log.Fatalf("Error analyzing importance: %v", err)
	}

	fmt.Println("Analysis complete! Results written to enriched_kg_with_importance.json")
}
