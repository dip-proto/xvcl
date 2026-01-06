// Test: Constants and template expressions

backend example {
    .port = "443";
}

// Expression: boolean
set req.http.X-Enabled = "yes";

// Expression: arithmetic
set req.http.X-Port = "886";
