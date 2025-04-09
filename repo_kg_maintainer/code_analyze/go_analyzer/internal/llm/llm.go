package llm

// This package provides LLM-based code analysis capabilities

// LLMImportanceCalculator represents a system that uses LLM to calculate
// the importance of code components in a hierarchical manner
type LLMImportanceCalculator interface {
	// CalculatePackageImportance determines the importance of packages
	CalculatePackageImportance(enrichedGraphPath string) error

	// CalculateStructImportance determines the importance of structs based on important packages
	CalculateStructImportance(packagesToAnalyze []string) error

	// CalculateFunctionImportance determines the importance of functions based on important structs
	CalculateFunctionImportance(structsToAnalyze []string) error

	// WriteImportanceScores writes calculated scores back to the knowledge graph
	WriteImportanceScores(outputPath string) error
}
