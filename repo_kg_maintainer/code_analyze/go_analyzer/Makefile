# Go parameters
GOCMD=go
GOBUILD=$(GOCMD) build
GOCLEAN=$(GOCMD) clean
GOTEST=$(GOCMD) test
GOGET=$(GOCMD) get
GOMOD=$(GOCMD) mod
GOLINES=golines

# Binary names
BINARY_CALLGRAPH=callgraph
BINARY_DOT=dot
BINARY_KG=kg
BINARY_KGSERV=kgserv
BINARY_PAGERANK=pagerank
BINARY_IMPORTANCE=importance
BINARY_TAGGING=tagging

# Build directory
BUILD_DIR=build

# Main build directory creation
$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

# Format code using golines
.PHONY: format
format:
	$(GOLINES) -w .

# Build all binaries
.PHONY: all
all: clean $(BUILD_DIR) deps build-callgraph build-dot build-kg build-kgserv build-pagerank build-importance build-tagging

# Build callgraph binary
.PHONY: build-callgraph
build-callgraph: $(BUILD_DIR)
	cd cmd/callgraph && $(GOBUILD) -o ../../$(BUILD_DIR)/$(BINARY_CALLGRAPH) -v .

# Build dot binary
.PHONY: build-dot
build-dot: $(BUILD_DIR)
	cd cmd/dot && $(GOBUILD) -o ../../$(BUILD_DIR)/$(BINARY_DOT) -v .

# Build kg binary
.PHONY: build-kg
build-kg: $(BUILD_DIR)
	cd cmd/kg && $(GOBUILD) -o ../../$(BUILD_DIR)/$(BINARY_KG) -v .

# Build kgserv binary
.PHONY: build-kgserv
build-kgserv: $(BUILD_DIR)
	cd cmd/kgserv && $(GOBUILD) -o ../../$(BUILD_DIR)/$(BINARY_KGSERV) -v .

# Build pagerank binary
.PHONY: build-pagerank
build-pagerank: $(BUILD_DIR)
	cd cmd/pagerank && $(GOBUILD) -o ../../$(BUILD_DIR)/$(BINARY_PAGERANK) -v .

# Build importance binary
.PHONY: build-importance
build-importance: $(BUILD_DIR)
	cd cmd/importance && $(GOBUILD) -o ../../$(BUILD_DIR)/$(BINARY_IMPORTANCE) -v .

# Build tagging binary
.PHONY: build-tagging
build-tagging: $(BUILD_DIR)
	cd cmd/tagging && $(GOBUILD) -o ../../$(BUILD_DIR)/$(BINARY_TAGGING) -v .

# Clean build files
.PHONY: clean
clean:
	$(GOCLEAN)
	rm -rf $(BUILD_DIR)

# Run tests
.PHONY: test
test:
	$(GOTEST) -v ./...

# Run tests for internal packages
.PHONY: test-internal
test-internal:
	$(GOTEST) -v ./internal/...

# Lint
.PHONY: lint
lint: 
	golines -w .

# Update dependencies
.PHONY: deps
deps:
	$(GOMOD) download
	$(GOMOD) verify
	$(GOMOD) tidy

# Run callgraph binary
.PHONY: run-callgraph
run-callgraph: build-callgraph
	./$(BUILD_DIR)/$(BINARY_CALLGRAPH)

# Run dot binary
.PHONY: run-dot
run-dot: build-dot
	./$(BUILD_DIR)/$(BINARY_DOT)

# Run kg binary
.PHONY: run-kg
run-kg: build-kg
	./$(BUILD_DIR)/$(BINARY_KG)

# Run kgserv binary
.PHONY: run-kgserv
run-kgserv: build-kgserv
	./$(BUILD_DIR)/$(BINARY_KGSERV)

# Run pagerank binary
.PHONY: run-pagerank
run-pagerank: build-pagerank
	./$(BUILD_DIR)/$(BINARY_PAGERANK)

# Run importance binary
.PHONY: run-importance
run-importance: build-importance
	./$(BUILD_DIR)/$(BINARY_IMPORTANCE)

# Run tagging binary
.PHONY: run-tagging
run-tagging: build-tagging
	./$(BUILD_DIR)/$(BINARY_TAGGING)

# Build with specific tags (e.g., for production)
.PHONY: build-prod
build-prod: $(BUILD_DIR)
	cd cmd/callgraph && $(GOBUILD) -tags=production -o ../../$(BUILD_DIR)/$(BINARY_CALLGRAPH) -v .
	cd cmd/dot && $(GOBUILD) -tags=production -o ../../$(BUILD_DIR)/$(BINARY_DOT) -v .
	cd cmd/kg && $(GOBUILD) -tags=production -o ../../$(BUILD_DIR)/$(BINARY_KG) -v .
	cd cmd/kgserv && $(GOBUILD) -tags=production -o ../../$(BUILD_DIR)/$(BINARY_KGSERV) -v .
	cd cmd/pagerank && $(GOBUILD) -tags=production -o ../../$(BUILD_DIR)/$(BINARY_PAGERANK) -v .
	cd cmd/importance && $(GOBUILD) -tags=production -o ../../$(BUILD_DIR)/$(BINARY_IMPORTANCE) -v .
	cd cmd/tagging && $(GOBUILD) -tags=production -o ../../$(BUILD_DIR)/$(BINARY_TAGGING) -v .

# Install all binaries to $GOPATH/bin
.PHONY: install
install: all
	cp $(BUILD_DIR)/$(BINARY_CALLGRAPH) $(GOPATH)/bin/
	cp $(BUILD_DIR)/$(BINARY_DOT) $(GOPATH)/bin/
	cp $(BUILD_DIR)/$(BINARY_KG) $(GOPATH)/bin/
	cp $(BUILD_DIR)/$(BINARY_KGSERV) $(GOPATH)/bin/
	cp $(BUILD_DIR)/$(BINARY_PAGERANK) $(GOPATH)/bin/
	cp $(BUILD_DIR)/$(BINARY_IMPORTANCE) $(GOPATH)/bin/
	cp $(BUILD_DIR)/$(BINARY_TAGGING) $(GOPATH)/bin/
