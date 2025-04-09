package analyzer

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// Relationship represents a relationship between two entities
type Relationship struct {
	Caller         string
	Callee         string
	CallerFilePath string
	CalleeFilePath string
	RelationType   string // "calls" or "instantiates"
}

// StructMethod keeps track of methods belonging to structs
type StructMethod struct {
	StructName   string
	MethodName   string
	PackageName  string
	ReceiverName string
}

// TypeInfo stores information about a type
type TypeInfo struct {
	Filepath    string
	PackageName string
	TypeName    string
	IsPointer   bool
}

// VarInfo stores information about a variable
type VarInfo struct {
	Type     TypeInfo
	Scope    *ast.Scope // Track variable scope
	Position token.Pos  // Position in the file for scope resolution
}

// FunctionInfo stores information about a function's return type
type FunctionInfo struct {
	Filepath    string
	PackageName string
	ReturnType  TypeInfo
}

// Analyzer maintains the state during analysis
type Analyzer struct {
	// Map of package paths to package names
	Packages map[string]string
	// Map of function or method name to its full qualified name
	Functions map[string]FunctionInfo
	// Map of method name to struct it belongs to
	Methods map[string]StructMethod
	// List of discovered call relationships
	Relationships []Relationship
	// Current package being analyzed
	CurrentPackage string
	// Current function being analyzed
	CurrentFunction string
	// Map of imported package aliases to their full package paths
	Imports map[string]string
	// New fields for type tracking
	Types         map[string]TypeInfo // Map of type names to their full qualified names
	Variables     map[string]VarInfo  // Map of variable names to their type information
	CurrentScope  *ast.Scope          // Current scope being analyzed
	FileSet       *token.FileSet      // File set for position information
	TypeAliases   map[string]TypeInfo // Map of type aliases to their original types
	ImportedTypes map[string]TypeInfo // Map of imported type names to their full names
	// Track embedded types
	EmbeddedTypes map[string][]TypeInfo // Map of type name to its embedded types
	// Track global variables
	GlobalVars map[string]VarInfo // Map of global variable names to their type info
	// Track struct fields and their types
	StructFields map[string]map[string]TypeInfo // Map of struct name -> field name -> type info
	// Map of function name to its return type
	FunctionReturnTypes map[string]FunctionInfo
}

// GenerateCallGraph takes a directory path and returns an array of call relationships
func GenerateCallGraph(projectDir string) ([]Relationship, error) {
	analyzer := &Analyzer{
		Packages:            make(map[string]string),
		Functions:           make(map[string]FunctionInfo),
		Methods:             make(map[string]StructMethod),
		Relationships:       []Relationship{},
		Imports:             make(map[string]string),
		Types:               make(map[string]TypeInfo),
		Variables:           make(map[string]VarInfo),
		TypeAliases:         make(map[string]TypeInfo),
		ImportedTypes:       make(map[string]TypeInfo),
		EmbeddedTypes:       make(map[string][]TypeInfo),
		GlobalVars:          make(map[string]VarInfo),
		StructFields:        make(map[string]map[string]TypeInfo),
		FunctionReturnTypes: make(map[string]FunctionInfo),
	}

	// First pass: collect all packages, functions, and methods
	err := filepath.Walk(projectDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(path, ".go") && !strings.HasSuffix(path, "_test.go") {
			err = analyzer.analyzeFileForDeclarations(path)
			if err != nil {
				return fmt.Errorf("error analyzing declarations in %s: %v", path, err)
			}
		}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("error in first pass: %v", err)
	}

	/* DEBUG
	fmt.Printf("analyzer.Packages: %+v\n", analyzer.Packages)
	for typename, t := range analyzer.Types {
		fmt.Printf("analyzer.Types: %s: %+v\n", typename, t)
	}
	for funcName, funcInfo := range analyzer.Functions {
		fmt.Printf("analyzer.Functions: %s: %+v\n", funcName, funcInfo)
	}
	for methodName, methodInfo := range analyzer.Methods {
		fmt.Printf("analyzer.Methods: %s: %+v\n", methodName, methodInfo)
	} */

	// Second pass: analyze function calls
	err = filepath.Walk(projectDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && strings.HasSuffix(path, ".go") && !strings.HasSuffix(path, "_test.go") {
			err = analyzer.analyzeFileForCalls(path)
			if err != nil {
				return fmt.Errorf("error analyzing calls in %s: %v", path, err)
			}
		}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("error in second pass: %v", err)
	}

	return analyzer.Relationships, nil
}

// analyzeFileForDeclarations collects functions, methods, and packages
func (a *Analyzer) analyzeFileForDeclarations(filePath string) error {
	fset := token.NewFileSet()
	a.FileSet = fset
	node, err := parser.ParseFile(fset, filePath, nil, parser.ParseComments)
	if err != nil {
		return err
	}

	// Initialize scope
	a.CurrentScope = node.Scope

	packageName := node.Name.Name
	packagePath := filepath.Dir(filePath)
	a.Packages[packagePath] = packageName

	// Process imports
	for _, imp := range node.Imports {
		importPath := strings.Trim(imp.Path.Value, "\"")

		// Handle named imports (e.g., "import fmt \"fmt\"")
		var importName string
		if imp.Name != nil {
			importName = imp.Name.Name
		} else {
			// For regular imports, use the last part of the path
			parts := strings.Split(importPath, "/")
			importName = parts[len(parts)-1]
		}

		a.Imports[importName] = importPath
	}

	// Process type declarations
	ast.Inspect(node, func(n ast.Node) bool {
		switch x := n.(type) {
		case *ast.TypeSpec:
			a.processTypeDeclaration(x, packageName)
		case *ast.GenDecl:
			if x.Tok == token.VAR || x.Tok == token.CONST {
				a.processVarDeclaration(x, packageName)
			}
		case *ast.FuncDecl:
			a.processFuncDeclaration(x, packageName)
		}
		return true
	})

	return nil
}

func (a *Analyzer) processTypeDeclaration(typeSpec *ast.TypeSpec, packageName string) {
	typeName := typeSpec.Name.Name
	fmt.Printf("processTypeDeclaration typeName: %s; packageName: %s\n", typeName, packageName)
	fmt.Printf("typeSpec.Type: %+v\n", typeSpec.Type)

	switch t := typeSpec.Type.(type) {
	case *ast.StructType:
		a.Types[fmt.Sprintf("%s.%s", packageName, typeName)] = TypeInfo{
			Filepath:    a.FileSet.Position(typeSpec.Pos()).Filename,
			PackageName: packageName,
			TypeName:    typeName,
			IsPointer:   false,
		}
		// Process embedded types
		a.processStructType(typeSpec, t, packageName)
	case *ast.Ident:
		// Handle type aliases
		a.TypeAliases[fmt.Sprintf("%s.%s", packageName, typeName)] = TypeInfo{
			Filepath:    a.FileSet.Position(typeSpec.Pos()).Filename,
			PackageName: packageName,
			TypeName:    t.Name,
			IsPointer:   false,
		}
	case *ast.StarExpr:
		// Handle pointer type aliases
		if ident, ok := t.X.(*ast.Ident); ok {
			a.TypeAliases[fmt.Sprintf("%s.%s", packageName, typeName)] = TypeInfo{
				Filepath:    a.FileSet.Position(typeSpec.Pos()).Filename,
				PackageName: packageName,
				TypeName:    ident.Name,
				IsPointer:   true,
			}
		}
	case *ast.InterfaceType:
		a.Types[fmt.Sprintf("%s.%s", packageName, typeName)] = TypeInfo{
			Filepath:    a.FileSet.Position(typeSpec.Pos()).Filename,
			PackageName: packageName,
			TypeName:    typeName,
			IsPointer:   false,
		}
	default:
		fmt.Printf("Unknown type: %T\n", t)
		a.Types[fmt.Sprintf("%s.%s", packageName, typeName)] = TypeInfo{
			Filepath:    a.FileSet.Position(typeSpec.Pos()).Filename,
			PackageName: packageName,
			TypeName:    typeName,
			IsPointer:   false,
		}
	}
}

func (a *Analyzer) processStructType(
	typeSpec *ast.TypeSpec,
	structType *ast.StructType,
	packageName string,
) {
	typeName := typeSpec.Name.Name

	// Initialize field map for this struct if not exists
	if _, ok := a.StructFields[typeName]; !ok {
		a.StructFields[typeName] = make(map[string]TypeInfo)
	}

	for _, field := range structType.Fields.List {
		if len(field.Names) == 0 {
			// Handle embedded fields
			continue
		}

		fieldType := a.resolveTypeFromExpr(field.Type, packageName)
		for _, name := range field.Names {
			a.StructFields[typeName][name.Name] = fieldType

			// If this is an imported type, add it to ImportedTypes
			if fieldType.PackageName != packageName {
				a.ImportedTypes[fieldType.TypeName] = fieldType
			}
		}
	}
}

func (a *Analyzer) processVarDeclaration(decl *ast.GenDecl, packageName string) {
	for _, spec := range decl.Specs {
		if valueSpec, ok := spec.(*ast.ValueSpec); ok {
			typeInfo := a.resolveTypeFromExpr(valueSpec.Type, packageName)

			for i, name := range valueSpec.Names {
				varInfo := VarInfo{
					Type:     typeInfo,
					Scope:    a.CurrentScope,
					Position: name.Pos(),
				}

				// If there's an initial value, try to get type from it
				if valueSpec.Values != nil && i < len(valueSpec.Values) {
					if inferredType := a.inferTypeFromValue(valueSpec.Values[i]); inferredType.TypeName != "" {
						varInfo.Type = inferredType
					}
				}

				// If we're at package level (no current scope or in the top-level scope),
				// this is a global variable
				if a.CurrentScope == nil {
					a.GlobalVars[name.Name] = varInfo
				}

				a.Variables[name.Name] = varInfo
			}
		}
	}
}

func (a *Analyzer) processFuncDeclaration(funcDecl *ast.FuncDecl, packageName string) {
	// Add the function to our known functions map
	if funcDecl.Recv == nil {
		a.Functions[fmt.Sprintf("%s.%s", packageName, funcDecl.Name.Name)] = FunctionInfo{
			Filepath:    a.FileSet.Position(funcDecl.Pos()).Filename,
			PackageName: packageName,
		}

		// Store the return type if available
		if funcDecl.Type.Results != nil && len(funcDecl.Type.Results.List) > 0 {
			returnType := a.resolveTypeFromExpr(funcDecl.Type.Results.List[0].Type, packageName)
			a.FunctionReturnTypes[funcDecl.Name.Name] = FunctionInfo{
				PackageName: packageName,
				ReturnType:  returnType,
			}
		}
	}

	// Create new scope for function
	functionScope := ast.NewScope(a.CurrentScope)

	// Process receiver type if it's a method
	if funcDecl.Recv != nil {
		for _, field := range funcDecl.Recv.List {
			typeInfo := a.resolveTypeFromExpr(field.Type, packageName)
			// Store method with receiver name
			if len(field.Names) > 0 {
				receiverName := field.Names[0].Name
				a.Methods[fmt.Sprintf("%s.%s.%s", packageName, typeInfo.TypeName, funcDecl.Name.Name)] = StructMethod{
					StructName:   typeInfo.TypeName,
					MethodName:   funcDecl.Name.Name,
					PackageName:  packageName,
					ReceiverName: receiverName,
				}
				// Store receiver variable type
				a.Variables[receiverName] = VarInfo{
					Type:     typeInfo,
					Scope:    functionScope,
					Position: field.Pos(),
				}
			}
		}
	}

	// Process parameters
	if funcDecl.Type.Params != nil {
		for _, field := range funcDecl.Type.Params.List {
			typeInfo := a.resolveTypeFromExpr(field.Type, packageName)
			for _, name := range field.Names {
				a.Variables[name.Name] = VarInfo{
					Type:     typeInfo,
					Scope:    functionScope,
					Position: name.Pos(),
				}
			}
		}
	}

	// Process function body
	if funcDecl.Body != nil {
		// Save the current scope and restore it after processing the function
		oldScope := a.CurrentScope
		a.CurrentScope = functionScope

		ast.Inspect(funcDecl.Body, func(n ast.Node) bool {
			a.processNode(n, packageName)
			return true
		})

		// Restore the original scope
		a.CurrentScope = oldScope
	}
}

func (a *Analyzer) processNode(node ast.Node, packageName string) {
	switch x := node.(type) {
	case *ast.AssignStmt:
		a.processAssignment(x, packageName)
	case *ast.RangeStmt:
		a.processRangeStmt(x, packageName)
	case *ast.TypeSwitchStmt:
		a.processTypeSwitchStmt(x, packageName)
	}
}

func (a *Analyzer) resolveVariableType(ident *ast.Ident) string {
	// First try existing resolution methods
	if varType := a.resolveExistingVariable(ident); varType != "" {
		return varType
	}

	// If we're in a method receiver context, check struct fields
	if a.CurrentFunction != "" {
		parts := strings.Split(a.CurrentFunction, ".")
		if len(parts) >= 2 {
			structName := parts[len(parts)-2] // Get the struct name from current function
			if fields, ok := a.StructFields[structName]; ok {
				if fieldType, ok := fields[ident.Name]; ok {
					if fieldType.PackageName != "" {
						return fmt.Sprintf("%s.%s", fieldType.PackageName, fieldType.TypeName)
					}
				}
			}
		}
	}

	return ""
}

// Helper function to handle existing variable resolution logic
func (a *Analyzer) resolveExistingVariable(ident *ast.Ident) string {
	// First check if this is a receiver variable in a method
	if a.CurrentFunction != "" {
		parts := strings.Split(a.CurrentFunction, ".")
		if len(parts) >= 2 {
			// We're in a method, check if this is the receiver variable
			structName := parts[len(parts)-2] // Get the struct name from current function
			if method, ok := a.Methods[fmt.Sprintf("%s.%s.%s", a.CurrentPackage, structName, parts[len(parts)-1])]; ok {
				// Verify this is a method of the current struct
				if method.StructName == structName && method.PackageName == a.CurrentPackage {
					// If this is the receiver variable
					if ident.Name == method.ReceiverName {
						return fmt.Sprintf("%s.%s", method.PackageName, method.StructName)
					}
				}
			}
		}
	}

	// Then check other variables in current scope
	if varInfo, ok := a.Variables[ident.Name]; ok {
		// Check if the variable is in the current scope
		if varInfo.Type.PackageName != "" {
			return fmt.Sprintf("%s.%s", varInfo.Type.PackageName, varInfo.Type.TypeName)
		}
	}

	// Check global variables
	if varInfo, ok := a.GlobalVars[ident.Name]; ok {
		if varInfo.Type.PackageName != "" {
			return fmt.Sprintf("%s.%s", varInfo.Type.PackageName, varInfo.Type.TypeName)
		}
	}

	// Check if it's an imported type
	if typeInfo, ok := a.ImportedTypes[ident.Name]; ok {
		return fmt.Sprintf("%s.%s", typeInfo.PackageName, typeInfo.TypeName)
	}

	return ""
}

// Helper functions for type resolution
func (a *Analyzer) resolveTypeFromExpr(expr ast.Expr, packageName string) TypeInfo {
	if expr == nil {
		return TypeInfo{}
	}

	switch t := expr.(type) {
	case *ast.Ident:
		// Check if it's a known type
		if typeInfo, ok := a.Types[fmt.Sprintf("%s.%s", packageName, t.Name)]; ok {
			return typeInfo
		}
		// Check if it's an imported type
		if typeInfo, ok := a.ImportedTypes[t.Name]; ok {
			return typeInfo
		}
		return TypeInfo{PackageName: packageName, TypeName: t.Name}

	case *ast.StarExpr:
		baseType := a.resolveTypeFromExpr(t.X, packageName)
		baseType.IsPointer = true
		return baseType

	case *ast.SelectorExpr:
		if ident, ok := t.X.(*ast.Ident); ok {
			return TypeInfo{
				PackageName: ident.Name,
				TypeName:    t.Sel.Name,
			}
		}
	}

	return TypeInfo{}
}

// analyzeFileForCalls analyzes function calls
func (a *Analyzer) analyzeFileForCalls(filePath string) error {
	fset := token.NewFileSet()
	node, err := parser.ParseFile(fset, filePath, nil, parser.ParseComments)
	if err != nil {
		return err
	}

	packageName := node.Name.Name
	a.CurrentPackage = packageName

	// Process imports
	a.Imports = make(map[string]string) // Reset imports for this file
	for _, imp := range node.Imports {
		importPath := strings.Trim(imp.Path.Value, "\"")

		// Handle named imports (e.g., "import fmt \"fmt\"")
		var importName string
		if imp.Name != nil {
			importName = imp.Name.Name
		} else {
			// For regular imports, use the last part of the path
			parts := strings.Split(importPath, "/")
			importName = parts[len(parts)-1]
		}

		a.Imports[importName] = importPath
	}

	// Find all function calls
	ast.Inspect(node, func(n ast.Node) bool {
		switch x := n.(type) {
		case *ast.FuncDecl:
			// Set the current function we're analyzing
			if x.Recv == nil {
				a.CurrentFunction = fmt.Sprintf("%s.%s", packageName, x.Name.Name)
			} else {
				// Method
				var structName string
				switch recv := x.Recv.List[0].Type.(type) {
				case *ast.StarExpr:
					if ident, ok := recv.X.(*ast.Ident); ok {
						structName = ident.Name
					}
				case *ast.Ident:
					structName = recv.Name
				}
				if structName != "" {
					a.CurrentFunction = fmt.Sprintf("%s.%s.%s", packageName, structName, x.Name.Name)
				} else {
					a.CurrentFunction = fmt.Sprintf("%s.%s", packageName, x.Name.Name)
				}
			}

			// Analyze the function body for calls
			if x.Body != nil {
				ast.Inspect(x.Body, func(n ast.Node) bool {
					if call, ok := n.(*ast.CallExpr); ok {
						callee := a.getCalleeName(call.Fun)
						if callee != "" {
							calleeFilePath := ""
							found := false
							paths := []string{}
							for path, _ := range a.Packages {
								paths = append(paths, path)
							}
							sort.Strings(paths)
							for _, path := range paths {
								pkg := a.Packages[path]
								if strings.HasPrefix(callee, pkg+".") {
									// Find the most specific match by walking the directory
									fmt.Printf("Found pkg: %s for callee: %s. Walking directory %s...\n", pkg, callee, path)
									err := filepath.Walk(path, func(p string, info os.FileInfo, err error) error {
										if err != nil {
											return err
										}
										if !info.IsDir() && strings.HasSuffix(p, ".go") {
											// Check if this file contains the callee
											content, err := os.ReadFile(p)
											if err == nil {
												var funcPattern string
												trimmedCallee := strings.TrimPrefix(callee, pkg+".")
												if strings.Contains(trimmedCallee, ".") {
													parts := strings.Split(trimmedCallee, ".")
													structName := parts[0]
													methodName := parts[1]
													funcPattern = `func\s+\(\w+\s+(?:\*)?` + regexp.QuoteMeta(structName) + `\)\s+` + regexp.QuoteMeta(methodName) + `\(`
												} else {
													funcPattern = `func\s+(?:\([^)]+\)\s+)?` + regexp.QuoteMeta(trimmedCallee) + `\(`
												}
												matched, regexErr := regexp.Match(funcPattern, content)
												if regexErr == nil && matched {
													fmt.Printf("Found file: %s for callee: %s\n", p, callee)
													calleeFilePath = p
													found = true
												}
											}
										}
										return nil
									})
									if !found {
										fmt.Printf("Not found file for callee: %s\n", callee)
									} else {
										break
									}
									if err != nil {
										fmt.Printf("Error finding callee file: %v\n", err)
									}
								}
							}
							if !found {
								calleeFunctionInfo, ok := a.Functions[callee]
								if ok {
									calleeFilePath = calleeFunctionInfo.Filepath
								}
							}

							a.Relationships = append(a.Relationships, Relationship{
								Caller:         a.CurrentFunction,
								Callee:         callee,
								CallerFilePath: filePath,
								CalleeFilePath: calleeFilePath,
								RelationType:   "calls",
							})
						}
					}

					// CASE 1: Direct struct instantiation (ABCStruct{...})
					if compositeLit, ok := n.(*ast.CompositeLit); ok {
						structType := a.getStructTypeName(compositeLit.Type)
						if structType != "" {
							if typeInfo, ok := a.Types[structType]; ok {
								a.Relationships = append(a.Relationships, Relationship{
									Caller:         a.CurrentFunction,
									Callee:         structType,
									CallerFilePath: filePath,
									CalleeFilePath: typeInfo.Filepath,
									RelationType:   "instantiates",
								})
							} else {
								a.Relationships = append(a.Relationships, Relationship{
									Caller:         a.CurrentFunction,
									Callee:         structType,
									CallerFilePath: filePath,
									CalleeFilePath: "", // We can try to find this
									RelationType:   "instantiates",
								})
							}
						}
					}

					// CASE 2: Pointer struct instantiation (&ABCStruct{...})
					if unaryExpr, ok := n.(*ast.UnaryExpr); ok {
						if unaryExpr.Op == token.AND {
							if compositeLit, ok := unaryExpr.X.(*ast.CompositeLit); ok {
								structType := a.getStructTypeName(compositeLit.Type)
								if structType != "" {
									if typeInfo, ok := a.Types[structType]; ok {
										a.Relationships = append(a.Relationships, Relationship{
											Caller:         a.CurrentFunction,
											Callee:         structType,
											CallerFilePath: filePath,
											CalleeFilePath: typeInfo.Filepath,
											RelationType:   "instantiates",
										})
									} else {
										a.Relationships = append(a.Relationships, Relationship{
											Caller:         a.CurrentFunction,
											Callee:         structType,
											CallerFilePath: filePath,
											CalleeFilePath: "", // We can try to find this
											RelationType:   "instantiates",
										})
									}
								}
							}
						}
					}

					return true
				})
			}

		case *ast.GoStmt:
			// Handle goroutine calls
			call := x.Call
			callee := a.getCalleeName(call.Fun)
			if callee == "" {
				callee = "anonymous goroutine"
			}
			// Similar file path lookup for goroutines
			calleeFilePath := ""
			if callee != "anonymous goroutine" {
				found := false
				for path, pkg := range a.Packages {
					if strings.HasPrefix(callee, pkg+".") {
						// Similar file path lookup as above
						filepath.Walk(path, func(p string, info os.FileInfo, err error) error {
							if !info.IsDir() && strings.HasSuffix(p, ".go") {
								content, err := os.ReadFile(p)
								if err == nil && strings.Contains(string(content), strings.TrimPrefix(callee, pkg+".")) {
									calleeFilePath = p
									found = true
									return filepath.SkipAll
								}
							}
							return nil
						})
						break
					}
				}
				if !found {
					calleeFunctionInfo, ok := a.Functions[callee]
					if ok {
						calleeFilePath = calleeFunctionInfo.Filepath
					}
				}
			}

			a.Relationships = append(a.Relationships, Relationship{
				Caller:         a.CurrentFunction,
				Callee:         callee,
				CallerFilePath: filePath,
				CalleeFilePath: calleeFilePath,
				RelationType:   "calls",
			})
		default:
			if x != nil {
				fmt.Printf("Unknown node: %T\n", x)
			}
		}
		return true
	})

	return nil
}

// getCalleeName determines the name of the function or method being called
func (a *Analyzer) getCalleeName(expr ast.Expr) string {
	switch x := expr.(type) {
	case *ast.Ident:
		// Handle local function calls within the same package
		if _, ok := a.Functions[fmt.Sprintf("%s.%s", a.CurrentPackage, x.Name)]; ok {
			return fmt.Sprintf("%s.%s", a.CurrentPackage, x.Name)
		} else {
			fmt.Printf("Not found function: %s\n", x.Name)
		}
		return ""

	case *ast.SelectorExpr:
		// Handle nested selector expressions (e.g., v.StartTime.Equal)
		switch inner := x.X.(type) {
		case *ast.SelectorExpr:
			// Resolve the type of the inner selector first
			innerType := a.resolveNestedSelector(inner)
			if innerType != "" {
				parts := strings.Split(innerType, ".")
				if len(parts) == 2 {
					return fmt.Sprintf("%s.%s.%s", parts[0], parts[1], x.Sel.Name)
				}
			}

		case *ast.Ident:
			// Check if it's an imported package
			if importPath, ok := a.Imports[inner.Name]; ok {
				// Get the actual package name from the import path
				parts := strings.Split(importPath, "/")
				actualPkgName := parts[len(parts)-1]

				// Return using the actual package name, not the alias
				return fmt.Sprintf("%s.%s", actualPkgName, x.Sel.Name)
			}

			// Try to resolve the type of the variable
			varType := a.resolveVariableType(inner)
			if varType != "" {
				parts := strings.Split(varType, ".")
				if len(parts) == 2 {
					pkgName, typeName := parts[0], parts[1]

					// Check if this type has the method
					if method, ok := a.Methods[fmt.Sprintf("%s.%s.%s", pkgName, typeName, x.Sel.Name)]; ok {
						if method.StructName == typeName {
							return fmt.Sprintf("%s.%s.%s", pkgName, typeName, x.Sel.Name)
						}
					}

					// Check embedded types
					if embedded, ok := a.EmbeddedTypes[typeName]; ok {
						for _, embType := range embedded {
							if method, ok := a.Methods[fmt.Sprintf("%s.%s.%s", embType.PackageName, embType.TypeName, x.Sel.Name)]; ok {
								if method.StructName == embType.TypeName {
									return fmt.Sprintf("%s.%s.%s", embType.PackageName, embType.TypeName, x.Sel.Name)
								}
							}
						}
					}
				}
				return fmt.Sprintf("%s.%s", varType, x.Sel.Name)
			}
		default:
			fmt.Printf("Unknown type: %T\n", x)
		}
	}
	return ""
}

// resolveNestedSelector resolves nested selector expressions
func (a *Analyzer) resolveNestedSelector(sel *ast.SelectorExpr) string {
	if ident, ok := sel.X.(*ast.Ident); ok {
		// First resolve the base variable type
		baseType := a.resolveVariableType(ident)

		if baseType != "" {
			parts := strings.Split(baseType, ".")
			if len(parts) == 2 {
				pkgName, typeName := parts[0], parts[1]

				// Look up the field type in the struct
				if fields, ok := a.StructFields[typeName]; ok {
					if fieldType, ok := fields[sel.Sel.Name]; ok {
						// Use the package name from the field type if available
						if fieldType.PackageName != "" {
							return fmt.Sprintf("%s.%s", fieldType.PackageName, fieldType.TypeName)
						}
						// Fall back to the base type's package name
						return fmt.Sprintf("%s.%s", pkgName, fieldType.TypeName)
					}
				}
			}
		}
	}
	return ""
}

// inferTypeFromValue attempts to determine the type of a value expression
func (a *Analyzer) inferTypeFromValue(expr ast.Expr) TypeInfo {
	switch x := expr.(type) {
	case *ast.CallExpr:
		// Handle function calls that return values
		switch fun := x.Fun.(type) {
		case *ast.Ident:
			// Look up the function's return type from our stored information
			if funcInfo, ok := a.FunctionReturnTypes[fun.Name]; ok {
				return funcInfo.ReturnType
			}

			// Handle built-in functions
			switch fun.Name {
			case "new":
				if len(x.Args) > 0 {
					return a.resolveTypeFromExpr(x.Args[0], a.CurrentPackage)
				}
			case "make":
				if len(x.Args) > 0 {
					return a.resolveTypeFromExpr(x.Args[0], a.CurrentPackage)
				}
			}
		case *ast.SelectorExpr:
			// Try to resolve the return type from package functions
			if ident, ok := fun.X.(*ast.Ident); ok {
				if _, ok := a.Imports[ident.Name]; ok {
					return TypeInfo{
						Filepath:    a.FileSet.Position(fun.Pos()).Filename,
						PackageName: ident.Name,
						TypeName:    fun.Sel.Name,
					}
				}
			}
		}

	case *ast.CompositeLit:
		// Handle composite literals (e.g., MyType{}, &MyType{})
		return a.resolveTypeFromExpr(x.Type, a.CurrentPackage)

	case *ast.UnaryExpr:
		// Handle address-of operator (&)
		if x.Op == token.AND {
			baseType := a.inferTypeFromValue(x.X)
			baseType.IsPointer = true
			return baseType
		}

	case *ast.Ident:
		// Handle simple identifiers
		if x.Obj != nil {
			switch decl := x.Obj.Decl.(type) {
			case *ast.ValueSpec:
				if decl.Type != nil {
					return a.resolveTypeFromExpr(decl.Type, a.CurrentPackage)
				}
			}
		}
		// Check if it's a known type being used as a value
		if typeInfo, ok := a.Types[fmt.Sprintf("%s.%s", a.CurrentPackage, x.Name)]; ok {
			return typeInfo
		}

	case *ast.SelectorExpr:
		// Handle package.Type expressions
		if ident, ok := x.X.(*ast.Ident); ok {
			return TypeInfo{
				Filepath:    a.FileSet.Position(x.Pos()).Filename,
				PackageName: ident.Name,
				TypeName:    x.Sel.Name,
			}
		}

	case *ast.BasicLit:
		// Handle basic literals
		switch x.Kind {
		case token.INT:
			return TypeInfo{Filepath: a.FileSet.Position(x.Pos()).Filename, PackageName: "builtin", TypeName: "int"}
		case token.FLOAT:
			return TypeInfo{Filepath: a.FileSet.Position(x.Pos()).Filename, PackageName: "builtin", TypeName: "float64"}
		case token.STRING:
			return TypeInfo{Filepath: a.FileSet.Position(x.Pos()).Filename, PackageName: "builtin", TypeName: "string"}
		case token.CHAR:
			return TypeInfo{Filepath: a.FileSet.Position(x.Pos()).Filename, PackageName: "builtin", TypeName: "rune"}
		}
	}

	return TypeInfo{}
}

// processAssignment handles assignment statements to track variable types
func (a *Analyzer) processAssignment(assign *ast.AssignStmt, packageName string) {
	// Handle := declarations
	isDeclaration := assign.Tok == token.DEFINE

	for i, lhs := range assign.Lhs {
		if ident, ok := lhs.(*ast.Ident); ok {
			var typeInfo TypeInfo

			// Get type from right-hand side if available
			if i < len(assign.Rhs) {
				typeInfo = a.inferTypeFromValue(assign.Rhs[i])
			}

			// Only create new variable info for declarations or if type was successfully inferred
			if isDeclaration || typeInfo.TypeName != "" {
				a.Variables[ident.Name] = VarInfo{
					Type:     typeInfo,
					Scope:    a.CurrentScope,
					Position: ident.Pos(),
				}
			}
		}
	}
}

// processRangeStmt handles type inference in for-range loops
func (a *Analyzer) processRangeStmt(rangeStmt *ast.RangeStmt, packageName string) {
	// Infer type of the range expression
	exprType := a.inferTypeFromValue(rangeStmt.X)

	// Handle key variable
	if rangeStmt.Key != nil {
		if ident, ok := rangeStmt.Key.(*ast.Ident); ok {
			var keyType TypeInfo
			switch {
			case exprType.TypeName == "string":
				keyType = TypeInfo{PackageName: "builtin", TypeName: "int"}
			case strings.HasPrefix(exprType.TypeName, "map["):
				// For maps, key type would depend on the map's key type
				// This is a simplified version; you might want to parse the map type more carefully
				keyType = TypeInfo{PackageName: "builtin", TypeName: "interface{}"}
			default:
				keyType = TypeInfo{PackageName: "builtin", TypeName: "int"}
			}

			a.Variables[ident.Name] = VarInfo{
				Type:     keyType,
				Scope:    a.CurrentScope,
				Position: ident.Pos(),
			}
		}
	}

	// Handle value variable
	if rangeStmt.Value != nil {
		if ident, ok := rangeStmt.Value.(*ast.Ident); ok {
			var valueType TypeInfo
			switch {
			case exprType.TypeName == "string":
				valueType = TypeInfo{PackageName: "builtin", TypeName: "rune"}
			case strings.HasPrefix(exprType.TypeName, "map["):
				// For maps, value type would be the map's value type
				// This is a simplified version
				valueType = TypeInfo{PackageName: "builtin", TypeName: "interface{}"}
			case strings.HasPrefix(exprType.TypeName, "[]"):
				// For slices, value type would be the element type
				// Remove the "[]" prefix to get the element type
				elemType := strings.TrimPrefix(exprType.TypeName, "[]")
				valueType = TypeInfo{PackageName: exprType.PackageName, TypeName: elemType}
			default:
				valueType = TypeInfo{PackageName: "builtin", TypeName: "interface{}"}
			}

			a.Variables[ident.Name] = VarInfo{
				Type:     valueType,
				Scope:    a.CurrentScope,
				Position: ident.Pos(),
			}
		}
	}
}

// processTypeSwitchStmt handles type switches to track variable types in each case
func (a *Analyzer) processTypeSwitchStmt(typeSwitch *ast.TypeSwitchStmt, packageName string) {
	// Get the variable name from the type switch assignment
	var switchVar string
	if assign, ok := typeSwitch.Assign.(*ast.AssignStmt); ok {
		if len(assign.Lhs) > 0 {
			if ident, ok := assign.Lhs[0].(*ast.Ident); ok {
				switchVar = ident.Name
			}
		}
	}

	// Process each case
	for _, stmt := range typeSwitch.Body.List {
		caseClause, ok := stmt.(*ast.CaseClause)
		if !ok {
			continue
		}

		// Skip default case
		if len(caseClause.List) == 0 {
			continue
		}

		// Create new scope for this case
		caseScope := ast.NewScope(a.CurrentScope)

		// Get the type for this case
		typeExpr := caseClause.List[0]
		caseType := a.resolveTypeFromExpr(typeExpr, packageName)

		// If we have a variable name, create a new variable info for this scope
		if switchVar != "" {
			a.Variables[switchVar] = VarInfo{
				Type:     caseType,
				Scope:    caseScope,
				Position: caseClause.Pos(),
			}
		}

		// Save the current scope and restore it after processing the case
		oldScope := a.CurrentScope
		a.CurrentScope = caseScope

		// Recursively process the case body
		for _, stmt := range caseClause.Body {
			ast.Inspect(stmt, func(n ast.Node) bool {
				a.processNode(n, packageName)
				return true
			})
		}

		// Restore the original scope
		a.CurrentScope = oldScope
	}
}

// getStructTypeName extracts the struct type name from an expression
func (a *Analyzer) getStructTypeName(expr ast.Expr) string {
	switch x := expr.(type) {
	case *ast.Ident:
		// Local struct type like "ABCStruct"
		return fmt.Sprintf("%s.%s", a.CurrentPackage, x.Name)

	case *ast.SelectorExpr:
		// Imported struct type like "pkg.ABCStruct"
		if ident, ok := x.X.(*ast.Ident); ok {
			return fmt.Sprintf("%s.%s", ident.Name, x.Sel.Name)
		}

	case *ast.StarExpr:
		// Pointer to struct type like "*ABCStruct"
		return a.getStructTypeName(x.X)
	}

	return ""
}
