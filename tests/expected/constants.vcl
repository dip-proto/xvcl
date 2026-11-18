// Test: Constants and template expressions

backend example {
    .port = "443";
}

// Expression: boolean
set req.http.X-Enabled = "yes";

// Expression: arithmetic
set req.http.X-Port = "886";

// Multi-line dict
set req.http.X-Port-web = "80";
set req.http.X-Port-api = "8080";
