package mcp

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/mark3labs/mcp-go/mcp"
)

func LsPackages(ctx context.Context, request mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	weightedKG := GetKnowledgeGraph()
	if weightedKG == nil {
		return nil, errors.New("knowledge graph not loaded")
	}

	// Find all package nodes
	var sb strings.Builder
	for _, node := range weightedKG.Nodes {
		if node.Type == "package" {
			sb.WriteString(fmt.Sprintf("Package id: %s\n", node.ID))
			var pkgName string
			if pkgData, ok := node.Data.(map[string]interface{}); ok {
				pkgName = pkgData["package_name"].(string)
			}

			sb.WriteString(
				fmt.Sprintf(
					"\t- Package %s has %d go files, %d structs, %d interfaces, %d functions, and %d sub packages\n",
					pkgName,
					node.Weights.GoFilesCount,
					node.Weights.StructCount,
					node.Weights.InterfaceCount,
					node.Weights.FunctionCount,
					node.Weights.SubpackageCount))
		}
	}
	sb.WriteString("\nYou can navigate to a specific package by using the package id.")

	return mcp.NewToolResultText(sb.String()), nil
}
