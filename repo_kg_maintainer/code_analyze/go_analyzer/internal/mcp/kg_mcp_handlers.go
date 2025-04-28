package mcp

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/tengteng/go-code-analyzer/internal/analyzer"
)

// Function variables for knowledge graph access to avoid import cycles
var (
	SetKnowledgeGraph func(*analyzer.WeightedKnowledgeGraph)
	GetKnowledgeGraph func() *analyzer.WeightedKnowledgeGraph
)

// GetImportantNodes returns nodes with importance above a specified threshold
func GetImportantNodes(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	threshold, ok := request.Params.Arguments["threshold"].(float64)
	if !ok {
		return nil, errors.New("threshold must be a number")
	}

	weightedKG := GetKnowledgeGraph()
	if weightedKG == nil {
		return nil, errors.New("knowledge graph not loaded")
	}

	// Find important nodes
	var importantNodes []map[string]interface{}
	for _, node := range weightedKG.Nodes {
		if node.Weights.Importance >= int(threshold) {
			nodeData := map[string]interface{}{
				"id":         node.ID,
				"type":       node.Type,
				"importance": node.Weights.Importance,
			}
			importantNodes = append(importantNodes, nodeData)
		}
	}

	// Convert to JSON
	resultJSON, err := json.Marshal(importantNodes)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal result: %v", err)
	}

	// Use the text function since we don't have a JSON-specific one
	return mcp.NewToolResultText(string(resultJSON)), nil
}
