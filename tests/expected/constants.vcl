// Test: Constants and template expressions
// Shared constants


backend example {
    .port = "443";
}

// Expression: boolean
set req.http.X-Enabled = "yes";

// Expression: arithmetic
set req.http.X-Port = "886";

// Constants from a file included earlier
set req.http.X-TTL = "7200";

// FLOAT literals never use exponent notation, but text in a string is left as Python writes it
set var.rate = 0.00005;
set var.rate = 10000000000000000.0;
set req.http.X-Rate = "5e-05";

// Multi-line dict
set req.http.X-Port-web = "80";
set req.http.X-Port-api = "8080";
