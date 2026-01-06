// Test: Inline macros

// Use macro with string literal
set req.http.X-Custom = "hello";

// Use macro with expression
set req.http.X-Other = req.http.Host;

// Multi-line macro

backend origin { .host = "origin.example.com"; .port = "443"; }
