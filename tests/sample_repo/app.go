package main

import "fmt"

type Server struct {
    Port int
}

func (s *Server) Start() {
    fmt.Println("Server starting on port", s.Port)
}

func main() {
    srv := &Server{Port: 8080}
    srv.Start()
}
