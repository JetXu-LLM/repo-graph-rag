package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"strings"

	"github.com/tengteng/go-code-analyzer/internal/analyzer"
	"github.com/tengteng/go-code-analyzer/internal/llm"
)

func main() {
	// Define flags
	kgPath := flag.String("graph", "enriched_kg_with_importance.json", "Path to the knowledge graph file")
	apiKey := flag.String("apikey", "", "OpenAI API key")
	model := flag.String("model", "gpt-4.1-mini", "OpenAI model")
	// debug := flag.Bool("debug", false, "Debug mode")
	// minLength := flag.Int("min_length", 3, "Minimum length of the paths to consider")
	pathsOutputFile := flag.String("paths", "paths.json", "Path to the output file")
	commonPathsOutputFile := flag.String("common_paths", "common_paths.json", "Path to the output file")

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

	// Convert knowledge graph to WeightedKnowledgeGraph
	skg, err := analyzer.LoadWeightedKnowledgeGraph(*kgPath)
	if err != nil {
		log.Fatalf("Error loading knowledge graph: %v", err)
		return
	}
	graph, entryNodes := WeightedKnowledgeGraphToGraph(skg, llmClient)
	// Find all paths with minimum length
	pathInfos := analyzer.FindLongPaths(graph, entryNodes)

	// Dump all paths to outputPath json file
	jsonData, err := json.MarshalIndent(pathInfos, "", "  ")
	if err != nil {
		log.Fatalf("Error marshalling paths: %v", err)
		return
	}
	os.WriteFile(*pathsOutputFile, jsonData, 0644)

	longestPathSize := len(pathInfos)
	if longestPathSize > 25 {
		longestPathSize = longestPathSize / 5
	}
	if longestPathSize > 10000 { // Limit the number of paths to 10000
		longestPathSize = 10000
	}
	// Only return top 20% longest paths
	pathInfos = pathInfos[:longestPathSize]

	// Find common paths
	paths := make([]analyzer.Path, 0)
	for _, pathInfo := range pathInfos {
		paths = append(paths, pathInfo.Path)
	}
	commonPaths := analyzer.CommonPathsCount(paths)
	jsonData, err = json.MarshalIndent(commonPaths, "", "  ")
	if err != nil {
		log.Fatalf("Error marshalling common paths: %v", err)
		return
	}
	os.WriteFile(*commonPathsOutputFile, jsonData, 0644)
}

// WeightedKnowledgeGraphToGraph converts a WeightedKnowledgeGraph to a Graph representation
// that can be used with FindLongPaths
// Only returns nodes with callee count 0 as entry nodes
func WeightedKnowledgeGraphToGraph(skg *analyzer.WeightedKnowledgeGraph, llmClient *llm.OpenAIClient) (analyzer.Graph, []string) {
	graph := make(analyzer.Graph)
	entryNodes := make([]string, 0)

	// Collect all function names
	functionNodes := make([]analyzer.WeightedNode, 0)
	for _, node := range skg.Nodes {
		if node.Type == analyzer.FunctionNode {
			functionNodes = append(functionNodes, node)
		}
	}

	// Send function names in batches to LLM to determine if they are utils functions
	batchSize := 100
	// functionTags is a map of function name to tags
	functionTags := make(map[string][]string)
	for i := 0; i < len(functionNodes); i += batchSize {
		batch := functionNodes[i:min(i+batchSize, len(functionNodes))]
		fmt.Println("Batch size:", len(batch))
		batchTags := llmClient.TagFunctions(batch)
		for funcName, tags := range batchTags {
			functionTags[funcName] = tags
		}
	}

	// Write function tags to file
	jsonData, err := json.MarshalIndent(functionTags, "", "  ")
	if err != nil {
		log.Fatalf("Error marshalling function tags: %v", err)
		return graph, entryNodes
	}
	os.WriteFile("function_tags.json", jsonData, 0644)

	// Write function names is utils information back to skg
	for i, node := range skg.Nodes {
		if node.Type == analyzer.FunctionNode {
			if nodeData, ok := node.Data.(map[string]interface{}); ok {
				packageAndFunctionName := nodeData["package_name"].(string) + "." + nodeData["function_name"].(string)
				if tags, ok := functionTags[packageAndFunctionName]; ok {
					skg.Nodes[i].Weights.Tags = tags
				} else {
					fmt.Println("No tags found for function:", packageAndFunctionName)
				}
			} else {
				fmt.Println("Node data is not a Function:", node.Data)
			}
		}
	}
	jsonData, err = json.MarshalIndent(skg, "", "  ")
	if err != nil {
		log.Fatalf("Error marshalling skg: %v", err)
		return graph, entryNodes
	}
	os.WriteFile("enriched_kg_with_importance_with_tags.json", jsonData, 0644)

	// Add all nodes to the graph
	for _, node := range skg.Nodes {
		if node.Type == analyzer.FunctionNode {
			isCoreLogic := true
			for _, tag := range node.Weights.Tags {
				if strings.ToLower(tag) == "utility" || strings.ToLower(tag) == "testing" {
					isCoreLogic = false
					break
				}
			}
			if !isCoreLogic {
				continue
			}
			graph[node.ID] = []string{}
			if node.Weights.CalleeCount == 0 {
				entryNodes = append(entryNodes, node.ID)
			}
		}
	}

	// Add edges to the graph
	for _, edge := range skg.Edges {
		if edge.RelationType == analyzer.Calls {
			if _, ok := graph[edge.SourceID]; ok {
				graph[edge.SourceID] = append(graph[edge.SourceID], edge.TargetID)
			}
		}
	}

	return graph, entryNodes
}
