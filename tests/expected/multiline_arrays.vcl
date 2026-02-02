// Test: Multi-line arrays

backend edge-1 {
    .port = "443";
}
backend edge-2 {
    .port = "443";
}

set req.http.X-Port = "80";
set req.http.X-Port = "443";
