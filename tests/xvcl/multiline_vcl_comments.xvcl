// Test: Multiline native VCL keeps line-comment boundaries

sub vcl_recv {
    if (
        req.method == "GET" // method is safe
        && req.url.path == "/"
    ) {
        set req.http.X-Matched = "1";
    }
}
