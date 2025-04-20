package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/tengteng/go-code-analyzer/internal/analyzer"
	kgparser "github.com/tengteng/go-code-analyzer/internal/parser"

	mapset "github.com/deckarep/golang-set/v2"
	sitter "github.com/smacker/go-tree-sitter"
	"github.com/smacker/go-tree-sitter/golang"
)

func main() {
	// Parse debug flag
	debug := false
	for _, arg := range os.Args[1:] {
		if arg == "--debug" {
			debug = true
			break
		}
	}

	if len(os.Args) < 2 {
		fmt.Println("Usage: program <project-path> [--debug]")
		os.Exit(1)
	}

	projectPath := os.Args[1]
	if projectPath == "--debug" {
		if len(os.Args) < 3 {
			fmt.Println("Usage: program <project-path> [--debug]")
			os.Exit(1)
		}
		projectPath = os.Args[2]
	}

	structuredKG := analyzer.StructuredKnowledgeGraph{
		Nodes: []analyzer.GraphNode{}, // Initialize as empty slice instead of map
		Edges: []analyzer.GraphEdge{}, // Initialize as empty slice instead of pointer slice
		Kg:    analyzer.NewKnowledgeGraph(),
	}
	parser := sitter.NewParser()
	language := golang.GetLanguage()
	parser.SetLanguage(language)

	if parser == nil || language == nil {
		fmt.Println("Failed to initialize parser or language")
		os.Exit(1)
	}

	// Walk through all Go files in the project. For each file we has 3 loops.
	err := filepath.Walk(projectPath, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(path, ".go") {
			if debug {
				fmt.Printf("Scanning file: %s\n", path)
			}
			if err := kgparser.ParseFile(path, parser, debug, &structuredKG); err != nil {
				fmt.Printf("Error parsing %s: %v\n", path, err)
			}
		}
		return nil
	})

	if err != nil {
		fmt.Printf("Error walking project: %v\n", err)
		os.Exit(1)
	}

	// Print the knowledge graph in std
	// This is for debugging purpose only, not for the final output knowledge_graph.json file
	analyzer.PrintKnowledgeGraph(structuredKG.Kg)

	// Generate the call graph
	relationships, err := analyzer.GenerateCallGraph(projectPath)
	if err != nil {
		fmt.Printf("Error generating call graph: %v\n", err)
		os.Exit(1)
	}
	if debug {
		// Sort relationships by Caller and Callee strings
		sort.Slice(relationships, func(i, j int) bool {
			if relationships[i].Caller == relationships[j].Callee {
				return relationships[i].Callee < relationships[j].Callee
			}
			return relationships[i].Caller < relationships[j].Caller
		})

		jsonData, err := json.MarshalIndent(relationships, "", "  ")
		if err != nil {
			fmt.Printf("Error marshalling call graph: %v\n", err)
			os.Exit(1)
		}
		os.WriteFile("callGraph.debug.json", jsonData, 0644)
	}

	// Add all node IDs to a set
	nodeIds := mapset.NewSet[string]()
	for _, node := range structuredKG.Nodes {
		nodeIds.Add(node.ID)
	}

	// Add the call graph to the knowledge graph
	existingCallEdges := mapset.NewSet[string]()
	for _, relationship := range relationships {
		rType := relationship.RelationType
		callerID, exists := analyzer.FindNodeID(
			nodeIds,
			relationship.CallerFilePath,
			relationship.Caller,
			rType,
			"caller",
		)
		if !exists {
			fmt.Printf(
				"Caller node not found: [function:%s:%s]\n",
				relationship.Caller,
				relationship.CallerFilePath,
			)
			continue
		}
		calleeID, exists := analyzer.FindNodeID(
			nodeIds,
			relationship.CalleeFilePath,
			relationship.Callee,
			rType,
			"callee",
		)
		foundInterfaceCall := false
		if !exists {
			// callee not found. This may be because the callee is a method in an interface.
			// Let's try another search
			calleeID, exists = analyzer.FindInterfaceNode(relationship.Callee, structuredKG.Nodes)
			if !exists {
				fmt.Printf(
					"Callee node not found: [function:%s:%s]\n",
					relationship.Callee,
					relationship.CalleeFilePath,
				)
				continue
			}
			foundInterfaceCall = true
		}

		// If this edge is already in the knowledge graph, skip it
		if existingCallEdges.Contains(fmt.Sprintf("%s:%s", callerID, calleeID)) {
			continue
		}
		if rType == "instantiates" {
			structuredKG.Edges = append(structuredKG.Edges, analyzer.GraphEdge{
				SourceType:   "function",
				SourceID:     callerID,
				TargetType:   "struct",
				TargetID:     calleeID,
				RelationType: analyzer.EdgeType(rType),
			})
		} else {
			if foundInterfaceCall {
				structuredKG.Edges = append(structuredKG.Edges, analyzer.GraphEdge{
					SourceType:   "function",
					SourceID:     callerID,
					TargetType:   "interface_function",
					TargetID:     calleeID,
					RelationType: analyzer.EdgeType(rType),
				})
			} else {
				structuredKG.Edges = append(structuredKG.Edges, analyzer.GraphEdge{
					SourceType:   "function",
					SourceID:     callerID,
					TargetType:   "function",
					TargetID:     calleeID,
					RelationType: analyzer.EdgeType(rType),
				})
			}
		}
		existingCallEdges.Add(fmt.Sprintf("%s:%s", callerID, calleeID))
	}
	// Save the structuredKG (which is a StructuredKnowledgeGraph) in knowledge_graph.json file
	if err := analyzer.SaveKnowledgeGraph(&structuredKG); err != nil {
		fmt.Printf("Error saving knowledge graph: %v\n", err)
	}
}
