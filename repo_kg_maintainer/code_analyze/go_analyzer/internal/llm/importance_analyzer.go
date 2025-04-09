package llm

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"

	"github.com/tengteng/go-code-analyzer/internal/analyzer"
)

// ImportanceAnalyzer evaluates the importance of code components
type ImportanceAnalyzer struct {
	LLMClient         LLMClient
	EnrichedGraph     analyzer.StructuredKnowledgeGraph
	ImportantNodes    map[string]int // Maps node IDs to importance scores
	PackageBatchSize  int
	StructBatchSize   int
	FunctionBatchSize int
}

// NewImportanceAnalyzerWithBatchSizes creates a new analyzer with configurable batch sizes
func NewImportanceAnalyzerWithBatchSizes(
	llmClient LLMClient,
	enrichedGraphPath string,
	packageBatchSize int,
	structBatchSize int,
	functionBatchSize int,
) (*ImportanceAnalyzer, error) {
	// Read enriched knowledge graph
	data, err := os.ReadFile(enrichedGraphPath)
	if err != nil {
		return nil, fmt.Errorf("error reading enriched graph file: %v", err)
	}

	var graph analyzer.StructuredKnowledgeGraph
	if err := json.Unmarshal(data, &graph); err != nil {
		return nil, fmt.Errorf("error parsing enriched graph JSON: %v", err)
	}

	return &ImportanceAnalyzer{
		LLMClient:         llmClient,
		EnrichedGraph:     graph,
		ImportantNodes:    make(map[string]int),
		PackageBatchSize:  packageBatchSize,
		StructBatchSize:   structBatchSize,
		FunctionBatchSize: functionBatchSize,
	}, nil
}

// NewImportanceAnalyzer creates a new analyzer with default batch sizes
func NewImportanceAnalyzer(llmClient LLMClient, enrichedGraphPath string) (*ImportanceAnalyzer, error) {
	return NewImportanceAnalyzerWithBatchSizes(
		llmClient,
		enrichedGraphPath,
		10, // Default package batch size
		10, // Default struct batch size
		10, // Default function batch size
	)
}

// AnalyzeImportance performs the hierarchical importance analysis
func (ia *ImportanceAnalyzer) AnalyzeImportance() error {
	// 1. Analyze package importance
	packageNodes, err := ia.getPackageNodes()
	if err != nil {
		return err
	}

	fmt.Printf("Analyzing %d packages in batches of %d...\n", len(packageNodes), ia.PackageBatchSize)
	if err := ia.processPackageBatch(packageNodes, ia.PackageBatchSize); err != nil {
		return err
	}

	// 2. Select top 20% important packages and analyze their structs
	topPackages := ia.getTopPackages(packageNodes, 0.2)
	structNodes, err := ia.getStructNodesFromPackages(topPackages)
	if err != nil {
		return err
	}

	fmt.Printf("Analyzing %d structs in batches of %d...\n", len(structNodes), ia.StructBatchSize)
	if err := ia.processStructBatch(structNodes, ia.StructBatchSize); err != nil {
		return err
	}

	// 3. Select top structs and analyze their methods and related functions
	topStructs := ia.getTopStructs(structNodes, 0.2)
	functionNodes, err := ia.getFunctionNodesFromStructs(topStructs)
	if err != nil {
		return err
	}

	fmt.Printf("Analyzing %d functions in batches of %d...\n", len(functionNodes), ia.FunctionBatchSize)
	if err := ia.processFunctionBatch(functionNodes, ia.FunctionBatchSize); err != nil {
		return err
	}

	// 4. Write importance scores back to the enriched graph
	return ia.writeImportanceScores()
}

// PackageInfo contains package metadata for importance evaluation
type PackageInfo struct {
	ID              string
	Name            string
	GoFilesCount    int
	StructCount     int
	FunctionCount   int
	ImportCount     int
	SubpackageCount int
}

// getPackageNodes extracts all package nodes with their metadata
func (ia *ImportanceAnalyzer) getPackageNodes() ([]PackageInfo, error) {
	var packages []PackageInfo

	for _, node := range ia.EnrichedGraph.Nodes {
		if node.Type == analyzer.PackageNode {
			pkg := PackageInfo{ID: node.ID}

			// Extract data from node
			data, ok := node.Data.(map[string]interface{})
			if !ok {
				continue
			}

			original, ok := data["original"].(map[string]interface{})
			if !ok {
				continue
			}

			if name, ok := original["package_name"].(string); ok {
				pkg.Name = name
			}

			weights, ok := data["weights"].(map[string]interface{})
			if !ok {
				continue
			}

			if count, ok := weights["go_files_count"].(float64); ok {
				pkg.GoFilesCount = int(count)
			}

			if count, ok := weights["struct_count"].(float64); ok {
				pkg.StructCount = int(count)
			}

			if count, ok := weights["function_count"].(float64); ok {
				pkg.FunctionCount = int(count)
			}

			if count, ok := weights["import_count"].(float64); ok {
				pkg.ImportCount = int(count)
			}

			if count, ok := weights["subpackage_count"].(float64); ok {
				pkg.SubpackageCount = int(count)
			}

			packages = append(packages, pkg)
		}
	}

	return packages, nil
}

// getTopPackages returns the top percentage of packages by importance score
func (ia *ImportanceAnalyzer) getTopPackages(packages []PackageInfo, topPercentage float64) []PackageInfo {
	if len(packages) == 0 {
		return []PackageInfo{}
	}

	// Sort packages by importance score
	sort.Slice(packages, func(i, j int) bool {
		return ia.ImportantNodes[packages[i].ID] > ia.ImportantNodes[packages[j].ID]
	})

	// Calculate how many packages to keep
	numToKeep := int(float64(len(packages)) * topPercentage)
	if numToKeep < 1 {
		numToKeep = 1
	}
	if numToKeep > len(packages) {
		numToKeep = len(packages)
	}

	return packages[:numToKeep]
}

// StructInfo contains struct metadata for importance evaluation
type StructInfo struct {
	ID             string
	PackageID      string
	Name           string
	FieldCount     int
	MethodCount    int
	ReferenceCount int
	InstanceCount  int
	CodeLineCount  int
}

// getStructNodesFromPackages extracts struct nodes from the given packages
func (ia *ImportanceAnalyzer) getStructNodesFromPackages(packages []PackageInfo) ([]StructInfo, error) {
	var structs []StructInfo
	packageIDs := make(map[string]bool)

	// Create set of package IDs
	for _, pkg := range packages {
		packageIDs[pkg.ID] = true
	}

	// Find structs belonging to these packages
	for _, edge := range ia.EnrichedGraph.Edges {
		if edge.RelationType == analyzer.HasStruct && packageIDs[edge.SourceID] {
			// Find the struct node
			for _, node := range ia.EnrichedGraph.Nodes {
				if node.ID == edge.TargetID && node.Type == analyzer.StructNode {
					s := StructInfo{
						ID:        node.ID,
						PackageID: edge.SourceID,
					}

					// Extract data from node
					data, ok := node.Data.(map[string]interface{})
					if !ok {
						continue
					}

					original, ok := data["original"].(map[string]interface{})
					if !ok {
						continue
					}

					if name, ok := original["struct_name"].(string); ok {
						s.Name = name
					}

					weights, ok := data["weights"].(map[string]interface{})
					if !ok {
						continue
					}

					if count, ok := weights["field_count"].(float64); ok {
						s.FieldCount = int(count)
					}

					if count, ok := weights["method_count"].(float64); ok {
						s.MethodCount = int(count)
					}

					if count, ok := weights["reference_count"].(float64); ok {
						s.ReferenceCount = int(count)
					}

					if count, ok := weights["total_instance_count"].(float64); ok {
						s.InstanceCount = int(count)
					}

					if count, ok := weights["code_line_count"].(float64); ok {
						s.CodeLineCount = int(count)
					}

					structs = append(structs, s)
				}
			}
		}
	}

	return structs, nil
}

// getTopStructs returns the top percentage of structs by importance score
func (ia *ImportanceAnalyzer) getTopStructs(structs []StructInfo, topPercentage float64) []StructInfo {
	if len(structs) == 0 {
		return []StructInfo{}
	}

	// Sort structs by importance score
	sort.Slice(structs, func(i, j int) bool {
		return ia.ImportantNodes[structs[i].ID] > ia.ImportantNodes[structs[j].ID]
	})

	// Calculate how many structs to keep
	numToKeep := int(float64(len(structs)) * topPercentage)
	if numToKeep < 1 {
		numToKeep = 1
	}
	if numToKeep > len(structs) {
		numToKeep = len(structs)
	}

	return structs[:numToKeep]
}

// FunctionInfo contains function metadata for importance evaluation
type FunctionInfo struct {
	ID                string
	StructID          string // Empty if not a method
	Name              string
	CodeLineCount     int
	CalleeCount       int // How many times this function is called
	CallerCount       int // How many functions this function calls
	InstantiatedCount int // Objects instantiated by this function
	IsSelfRecursive   bool
}

// getFunctionNodesFromStructs extracts function nodes related to the given structs
func (ia *ImportanceAnalyzer) getFunctionNodesFromStructs(structs []StructInfo) ([]FunctionInfo, error) {
	var functions []FunctionInfo
	structIDs := make(map[string]bool)

	// Create set of struct IDs
	for _, s := range structs {
		structIDs[s.ID] = true
	}

	// Find method functions belonging to these structs
	for _, edge := range ia.EnrichedGraph.Edges {
		if edge.RelationType == analyzer.HasMethod && structIDs[edge.SourceID] {
			// Find the function/method node
			for _, node := range ia.EnrichedGraph.Nodes {
				if node.ID == edge.TargetID && node.Type == analyzer.FunctionNode {
					f := FunctionInfo{
						ID:       node.ID,
						StructID: edge.SourceID,
					}

					// Extract data
					if functionData, err := ia.extractFunctionData(node); err == nil {
						f.Name = functionData.Name
						f.CodeLineCount = functionData.CodeLineCount
						f.CalleeCount = functionData.CalleeCount
						f.CallerCount = functionData.CallerCount
						f.InstantiatedCount = functionData.InstantiatedCount
						f.IsSelfRecursive = functionData.IsSelfRecursive

						functions = append(functions, f)
					}
				}
			}
		}
	}

	return functions, nil
}

// extractFunctionData extracts function metadata from a node
func (ia *ImportanceAnalyzer) extractFunctionData(node analyzer.GraphNode) (*FunctionInfo, error) {
	f := &FunctionInfo{
		ID: node.ID,
	}

	// Extract data from node
	data, ok := node.Data.(map[string]interface{})
	if !ok {
		return nil, fmt.Errorf("invalid function data format")
	}

	original, ok := data["original"].(map[string]interface{})
	if !ok {
		return nil, fmt.Errorf("missing original data")
	}

	if name, ok := original["function_name"].(string); ok {
		f.Name = name
	}

	weights, ok := data["weights"].(map[string]interface{})
	if !ok {
		return nil, fmt.Errorf("missing weights data")
	}

	if count, ok := weights["code_line_count"].(float64); ok {
		f.CodeLineCount = int(count)
	}

	if count, ok := weights["callee_count"].(float64); ok {
		f.CalleeCount = int(count)
	}

	if count, ok := weights["caller_count"].(float64); ok {
		f.CallerCount = int(count)
	}

	if count, ok := weights["instantiated_by_function"].(float64); ok {
		f.InstantiatedCount = int(count)
	}

	// Check for self-recursive label
	if labels, ok := weights["labels"].(map[string]interface{}); ok {
		if selfRecursive, ok := labels[string(analyzer.SelfRecursiveFunc)].(bool); ok {
			f.IsSelfRecursive = selfRecursive
		}
	}

	return f, nil
}

// writeImportanceScores writes the LLMImportance scores back to the enriched graph
func (ia *ImportanceAnalyzer) writeImportanceScores() error {
	// Update the nodes in the enriched graph with importance scores
	for i, node := range ia.EnrichedGraph.Nodes {
		if score, exists := ia.ImportantNodes[node.ID]; exists {
			// Get the existing data
			data, ok := node.Data.(map[string]interface{})
			if !ok {
				data = map[string]interface{}{}
			}

			// Get or create weights
			weights, ok := data["weights"].(map[string]interface{})
			if !ok {
				weights = map[string]interface{}{}
			}

			// Add LLMImportance score
			weights["LLMImportance"] = score

			// Update the data
			data["weights"] = weights
			ia.EnrichedGraph.Nodes[i].Data = data
		}
	}

	// Write the updated graph back to file
	enrichedData, err := json.MarshalIndent(ia.EnrichedGraph, "", "  ")
	if err != nil {
		return fmt.Errorf("error marshaling updated graph: %v", err)
	}

	if err := os.WriteFile("enriched_kg_with_importance.json", enrichedData, 0644); err != nil {
		return fmt.Errorf("error writing updated graph file: %v", err)
	}

	return nil
}

// processPackageBatch processes a batch of packages with LLM
func (ia *ImportanceAnalyzer) processPackageBatch(
	packages []PackageInfo,
	batchSize int,
) error {
	// Process in batches
	for i := 0; i < len(packages); i += batchSize {
		end := i + batchSize
		if end > len(packages) {
			end = len(packages)
		}

		batch := packages[i:end]
		prompt := ia.createPackagePrompt(batch)

		// Get LLM response for this batch
		response, err := ia.LLMClient.GetCompletion(prompt)
		if err != nil {
			return fmt.Errorf("error getting LLM response for package batch: %v", err)
		}

		// Process response
		if err := ia.processPackageResponse(response); err != nil {
			return fmt.Errorf("error processing package batch response: %v", err)
		}

		fmt.Printf("Processed package batch %d/%d (%d packages)\n",
			(i/batchSize)+1, (len(packages)-1)/batchSize+1, len(batch))
	}

	return nil
}

// createPackagePrompt creates a prompt for package importance analysis
func (ia *ImportanceAnalyzer) createPackagePrompt(batch []PackageInfo) string {
	var prompt strings.Builder
	prompt.WriteString("Based on the following Go packages information, assign an importance score to each package on a scale of 1-100.\n")
	prompt.WriteString("Consider metrics like number of Go files, structs, functions, imports, and subpackages. Higher numbers generally indicate more importance.\n")
	prompt.WriteString("Respond with ONLY a JSON object mapping package IDs to importance scores.\n\n")
	prompt.WriteString("Package information:\n")

	for _, pkg := range batch {
		packageInfo := fmt.Sprintf("Package ID: %s\nName: %s\nGo Files: %d\nStructs: %d\nFunctions: %d\nImports: %d\nSubpackages: %d\n\n",
			pkg.ID, pkg.Name, pkg.GoFilesCount, pkg.StructCount, pkg.FunctionCount, pkg.ImportCount, pkg.SubpackageCount)
		prompt.WriteString(packageInfo)
	}

	return prompt.String()
}

// processPackageResponse processes LLM response for package importance
func (ia *ImportanceAnalyzer) processPackageResponse(response string) error {
	scores := make(map[string]int)
	if err := json.Unmarshal([]byte(response), &scores); err != nil {
		return fmt.Errorf("error parsing LLM package importance scores: %v", err)
	}

	// Update importance scores
	for id, score := range scores {
		ia.ImportantNodes[id] = score
	}

	return nil
}

// processStructBatch processes a batch of structs with LLM
func (ia *ImportanceAnalyzer) processStructBatch(
	structs []StructInfo,
	batchSize int,
) error {
	// Process in batches
	for i := 0; i < len(structs); i += batchSize {
		end := i + batchSize
		if end > len(structs) {
			end = len(structs)
		}

		batch := structs[i:end]
		prompt := ia.createStructPrompt(batch)

		// Get LLM response for this batch
		response, err := ia.LLMClient.GetCompletion(prompt)
		if err != nil {
			return fmt.Errorf("error getting LLM response for struct batch: %v", err)
		}

		// Process response
		if err := ia.processStructResponse(response); err != nil {
			return fmt.Errorf("error processing struct batch response: %v", err)
		}

		fmt.Printf("Processed struct batch %d/%d (%d structs)\n",
			(i/batchSize)+1, (len(structs)-1)/batchSize+1, len(batch))
	}

	return nil
}

// createStructPrompt creates a prompt for struct importance analysis
func (ia *ImportanceAnalyzer) createStructPrompt(batch []StructInfo) string {
	var prompt strings.Builder
	prompt.WriteString("Based on the following Go structs information, assign an importance score to each struct on a scale of 1-100.\n")
	prompt.WriteString("Consider metrics like number of fields, methods, references, instances, and code line count. Higher numbers generally indicate more importance.\n")
	prompt.WriteString("Structs with many methods or that are frequently instantiated are likely more important.\n")
	prompt.WriteString("Respond with ONLY a JSON object mapping struct IDs to importance scores.\n\n")
	prompt.WriteString("Struct information:\n")

	for _, s := range batch {
		structInfo := fmt.Sprintf("Struct ID: %s\nPackage ID: %s\nName: %s\nFields: %d\nMethods: %d\nReferences: %d\nInstances: %d\nCode Lines: %d\n\n",
			s.ID, s.PackageID, s.Name, s.FieldCount, s.MethodCount, s.ReferenceCount, s.InstanceCount, s.CodeLineCount)
		prompt.WriteString(structInfo)
	}

	return prompt.String()
}

// processStructResponse processes LLM response for struct importance
func (ia *ImportanceAnalyzer) processStructResponse(response string) error {
	scores := make(map[string]int)
	if err := json.Unmarshal([]byte(response), &scores); err != nil {
		return fmt.Errorf("error parsing LLM struct importance scores: %v", err)
	}

	// Update importance scores
	for id, score := range scores {
		ia.ImportantNodes[id] = score
	}

	return nil
}

// processFunctionBatch processes a batch of functions with LLM
func (ia *ImportanceAnalyzer) processFunctionBatch(
	functions []FunctionInfo,
	batchSize int,
) error {
	// Process in batches
	for i := 0; i < len(functions); i += batchSize {
		end := i + batchSize
		if end > len(functions) {
			end = len(functions)
		}

		batch := functions[i:end]
		prompt := ia.createFunctionPrompt(batch)

		// Get LLM response for this batch
		response, err := ia.LLMClient.GetCompletion(prompt)
		if err != nil {
			return fmt.Errorf("error getting LLM response for function batch: %v", err)
		}

		// Process response
		if err := ia.processFunctionResponse(response); err != nil {
			return fmt.Errorf("error processing function batch response: %v", err)
		}

		fmt.Printf("Processed function batch %d/%d (%d functions)\n",
			(i/batchSize)+1, (len(functions)-1)/batchSize+1, len(batch))
	}

	return nil
}

// createFunctionPrompt creates a prompt for function importance analysis
func (ia *ImportanceAnalyzer) createFunctionPrompt(batch []FunctionInfo) string {
	var prompt strings.Builder
	prompt.WriteString("Based on the following Go functions information, assign an importance score to each function on a scale of 1-100.\n")
	prompt.WriteString("Consider metrics like number of callers, callees, instantiated objects, and code line count. Higher numbers generally indicate more importance.\n")
	prompt.WriteString("Functions that are called frequently or instantiate many objects are likely more important.\n")
	prompt.WriteString("Respond with ONLY a JSON object mapping function IDs to importance scores.\n\n")
	prompt.WriteString("Function information:\n")

	for _, f := range batch {
		structInfo := ""
		if f.StructID != "" {
			structInfo = fmt.Sprintf("Method of Struct ID: %s\n", f.StructID)
		}

		functionInfo := fmt.Sprintf("Function ID: %s\n%sName: %s\nCode Lines: %d\nCalled by others: %d\nCalls to others: %d\nObjects instantiated: %d\nSelf-recursive: %v\n\n",
			f.ID, structInfo, f.Name, f.CodeLineCount, f.CalleeCount, f.CallerCount, f.InstantiatedCount, f.IsSelfRecursive)
		prompt.WriteString(functionInfo)
	}

	return prompt.String()
}

// processFunctionResponse processes LLM response for function importance
func (ia *ImportanceAnalyzer) processFunctionResponse(response string) error {
	scores := make(map[string]int)
	if err := json.Unmarshal([]byte(response), &scores); err != nil {
		return fmt.Errorf("error parsing LLM function importance scores: %v", err)
	}

	// Update importance scores
	for id, score := range scores {
		ia.ImportantNodes[id] = score
	}

	return nil
}
