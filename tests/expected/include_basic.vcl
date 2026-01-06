// Test: Basic includes
// Shared constants

// Shared macros


// Backend definitions

backend F_origin1 {
    .host = "origin1.example.com";
    .port = "443";
}
backend F_origin2 {
    .host = "origin2.example.com";
    .port = "443";
}


// Use shared constants
backend F_main {
    .host = "api.example.com";
    .port = "8080";
}

// Use shared macro
sub vcl_recv {
    set req.http.X-TTL = req.http.Host;
    set req.http.X-TTL-Value = "3600";
}
