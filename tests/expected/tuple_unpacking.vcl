// Test: Tuple unpacking in for loops

// Two-element tuples
backend a { .port = "1"; }
backend b { .port = "2"; }

// Three-element tuples

backend us_east { .port = "443"; }
backend eu_west { .port = "8443"; }

// Enumerate with tuple unpacking

set req.http.X-User-0 = "alice";
set req.http.X-User-1 = "bob";

// Backward compatibility: single variable
backend web0 { }
backend web1 { }
