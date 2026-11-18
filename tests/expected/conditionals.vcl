// Test: Conditional compilation

// Simple if

// If-else
set req.http.X-Env = "prod";

// If-elif-else
set req.http.X-Version = "unknown";

// Nested conditionals
set req.http.X-Feature = "new";

// A comment that starts with "#if" isn't a nested block
set req.http.X-Debug = "off";
