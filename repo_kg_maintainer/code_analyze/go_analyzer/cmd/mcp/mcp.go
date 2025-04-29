package main

import (
	"flag"
	"fmt"
	"log"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/tengteng/go-code-analyzer/internal/analyzer"
	mcpHandler "github.com/tengteng/go-code-analyzer/internal/mcp"
)

// weightedKG stores the loaded knowledge graph for use by MCP handlers
var weightedKG *analyzer.WeightedKnowledgeGraph

func main() {
	// Define flags
	kgFile := flag.String("kg", "enriched_kg_with_importance.json", "Path to the enriched knowledge graph JSON file")
	flag.Parse()

	// Load the knowledge graph
	var err error
	weightedKG, err = analyzer.LoadWeightedKnowledgeGraph(*kgFile)
	if err != nil {
		log.Fatalf("Failed to load knowledge graph: %v", err)
	}

	// Make the knowledge graph available to MCP handlers
	mcpHandler.GetKnowledgeGraph = func() *analyzer.WeightedKnowledgeGraph {
		return weightedKG
	}

	fmt.Println("Go Pikachu!")
	s := server.NewMCPServer(
		"Demo 🚀",
		"1.0.0",
	)
	// Add ls packages
	lsPackages := mcp.NewTool(
		"list_packages",
		mcp.WithDescription("List all package names from the repository"),
		mcp.WithString("repoPath",
			mcp.Required(),
			mcp.Description("Path of the repository"),
		),
	)
	s.AddTool(lsPackages, mcpHandler.LsPackages)

	// Add get_important_nodes tool
	getImportantNodes := mcp.NewTool("get_important_nodes",
		mcp.WithDescription("Get nodes with importance above the specified threshold"),
		mcp.WithNumber("threshold",
			mcp.Required(),
			mcp.Description("Minimum importance threshold"),
		),
	)
	s.AddTool(getImportantNodes, mcpHandler.GetImportantNodes)

	// Add package go files tool
	lsPackageGoFiles := mcp.NewTool("list_package_files",
		mcp.WithDescription("List all Go files in a package"),
		mcp.WithString("packageID",
			mcp.Required(),
			mcp.Description("ID of the package"),
		),
	)
	s.AddTool(lsPackageGoFiles, mcpHandler.LsPackageGoFiles)

	// Add package functions tool
	lsPackageFunctions := mcp.NewTool("list_package_functions",
		mcp.WithDescription("List all functions in a package"),
		mcp.WithString("packageID",
			mcp.Required(),
			mcp.Description("ID of the package"),
		),
	)
	s.AddTool(lsPackageFunctions, mcpHandler.LsPackageFunctionNames)

	// Add package structs tool
	lsPackageStructs := mcp.NewTool("list_package_structs",
		mcp.WithDescription("List all structs in a package"),
		mcp.WithString("packageID",
			mcp.Required(),
			mcp.Description("ID of the package"),
		),
	)
	s.AddTool(lsPackageStructs, mcpHandler.LsPackageStructNames)

	// Add package interfaces tool
	lsPackageInterfaces := mcp.NewTool("list_package_interfaces",
		mcp.WithDescription("List all interfaces in a package"),
		mcp.WithString("packageID",
			mcp.Required(),
			mcp.Description("ID of the package"),
		),
	)
	s.AddTool(lsPackageInterfaces, mcpHandler.LsPackageInterfaceNames)

	// Add subpackages tool
	lsSubpackages := mcp.NewTool("list_subpackages",
		mcp.WithDescription("List all subpackages of a package"),
		mcp.WithString("packageID",
			mcp.Required(),
			mcp.Description("ID of the package"),
		),
	)
	s.AddTool(lsSubpackages, mcpHandler.LsSubpackages)

	// Start the stdio server
	if err := server.ServeStdio(s); err != nil {
		fmt.Printf("Server error: %v\n", err)
	}
}
