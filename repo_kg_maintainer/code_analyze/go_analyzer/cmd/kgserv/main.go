package main

import (
	"net/http"

	kghandlers "github.com/tengteng/go-code-analyzer/internal/handlers"

	"github.com/gin-gonic/gin"
)

type EdgeRequest struct {
	KGPath      string `json:"kgpath"`
	FileContent string `json:"fileContent"`
	FilePath    string `json:"filepath"`
}

func main() {
	r := gin.Default()

	r.POST("/nodes", kghandlers.SingleFileNodeHandler)

	r.POST("/edges", func(c *gin.Context) {
		var req EdgeRequest
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}

		// TODO: Implement edge processing logic
		c.JSON(http.StatusOK, gin.H{"message": "Edge processed successfully"})
	})

	if err := r.Run(":8080"); err != nil {
		panic(err)
	}
}
