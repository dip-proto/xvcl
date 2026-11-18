// Test: Conditional compilation

// Simple if

// If-else
set req.http.X-Env = "prod";

// If-elif-else: only the first true branch is kept
set req.http.X-Version = "v2";

// Nested conditionals
set req.http.X-Feature = "new";

// Multi-line #elif, with a nested block in the branch that is taken
set req.http.X-Range = "two";

// No branch taken

// A comment that starts with "#if" isn't a nested block
set req.http.X-Debug = "off";
