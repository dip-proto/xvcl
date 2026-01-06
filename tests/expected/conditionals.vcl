// Test: Conditional compilation

// Simple if

// If-else
set req.http.X-Env = "prod";

// If-elif-else
set req.http.X-Version = "unknown";

// Nested conditionals
set req.http.X-Feature = "new";
