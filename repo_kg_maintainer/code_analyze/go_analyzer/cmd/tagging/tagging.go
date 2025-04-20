package main

import (
	"encoding/json"
	"flag"
	"log"
	"os"

	"github.com/tengteng/go-code-analyzer/internal/analyzer"
)

func main() {
	// Define flags
	kgPath := flag.String("graph", "knowledge_graph.json", "Path to the knowledge graph file")
	// debug := flag.Bool("debug", false, "Debug mode")
	// minLength := flag.Int("min_length", 3, "Minimum length of the paths to consider")
	pathsOutputFile := flag.String("paths", "paths.json", "Path to the output file")
	commonPathsOutputFile := flag.String("common_paths", "common_paths.json", "Path to the output file")

	flag.Parse()

	// Convert knowledge graph to Graph
	skg, err := analyzer.LoadKnowledgeGraph(*kgPath)
	if err != nil {
		log.Fatalf("Error loading knowledge graph: %v", err)
		return
	}
	graph := analyzer.KnowledgeGraphToGraph(skg)
	// Find all paths with minimum length
	paths := analyzer.FindLongPaths(graph)

	// Dump all paths to outputPath json file
	jsonData, err := json.MarshalIndent(paths, "", "  ")
	if err != nil {
		log.Fatalf("Error marshalling paths: %v", err)
		return
	}
	os.WriteFile(*pathsOutputFile, jsonData, 0644)
	// Find common paths
	commonPaths := analyzer.CommonPathsCount(paths)
	jsonData, err = json.MarshalIndent(commonPaths, "", "  ")
	if err != nil {
		log.Fatalf("Error marshalling common paths: %v", err)
		return
	}
	os.WriteFile(*commonPathsOutputFile, jsonData, 0644)
}
