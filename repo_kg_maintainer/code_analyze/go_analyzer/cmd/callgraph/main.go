package main

import (
	"fmt"
	"os"

	"github.com/tengteng/go-code-analyzer/internal/analyzer"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Usage: go-call-graph <project-dir>")
		os.Exit(1)
	}

	projectDir := os.Args[1]
	relationships, err := analyzer.GenerateCallGraph(projectDir)
	if err != nil {
		fmt.Printf("Error generating call graph: %v\n", err)
		os.Exit(1)
	}

	fmt.Println("Function Call Relationships:")
	fmt.Println("----------------------------")
	for _, rel := range relationships {
		fmt.Printf("%s -> %s\n", rel.Caller, rel.Callee)
	}
}
