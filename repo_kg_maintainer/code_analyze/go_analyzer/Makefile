# Makefile for Go project

# Variables
GOFLAGS = -v
GOCMD = go
GOBUILD = $(GOCMD) build $(GOFLAGS)
GOCLEAN = $(GOCMD) clean
BINARY_KG = kg
BINARY_DOT = dot
BINARY_CALLGRAPH = callgraph
BINARY_PR = pagerank

.PHONY: all build clean help

# Default target
all: deps build

deps:
	$(GOCMD) mod download
	$(GOCMD) mod verify
	$(GOCMD) mod tidy

# Build both binaries
build: $(BINARY_KG) $(BINARY_DOT) $(BINARY_CALLGRAPH) $(BINARY_PR)

# Build the knowledge graph binary
$(BINARY_KG): ts.go knowledge_graph.go func_callgraph.go
	$(GOBUILD) -o $(BINARY_KG) ts.go knowledge_graph.go func_callgraph.go

# Build the knowledge graph binary
$(BINARY_DOT): dot.go knowledge_graph.go
	$(GOBUILD) -o $(BINARY_DOT) dot.go knowledge_graph.go

# Build the function callgraph binary
$(BINARY_CALLGRAPH): func_callgraph_main.go func_callgraph.go
	$(GOBUILD) -o $(BINARY_CALLGRAPH) func_callgraph_main.go func_callgraph.go

# Build the pagerank binary
$(BINARY_PR): pagerank.go knowledge_graph.go
	$(GOBUILD) -o $(BINARY_PR) pagerank.go knowledge_graph.go

# Clean the project
clean:
	$(GOCLEAN)
	rm -f $(BINARY_KG)
	rm -f $(BINARY_DOT)
	rm -f $(BINARY_CALLGRAPH)
	rm -f $(BINARY_PR)

# Show help
help:
	@echo "Available targets:"
	@echo "  make all          - Build all binaries (default)"
	@echo "  make build        - Build all binaries"
	@echo "  make clean        - Clean the project"
	@echo "  make kg    	   - Build only the knowledge graph binary"
	@echo "  make callgraph    - Build only the function callgraph binary"
	@echo "  make dot          - Build only the dot binary"
	@echo "  make pagerank     - Build only the pagerank binary"
	@echo "  make help         - Show this help message"
