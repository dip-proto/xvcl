// Test: Local variables with #let
sub vcl_recv {
    // Simple let with string
    declare local var.timestamp STRING;
    set var.timestamp = std.time(now, now);
    set req.http.X-Timestamp = var.timestamp;

    // Let with integer
    declare local var.counter INTEGER;
    set var.counter = 42;
    set req.http.X-Counter = var.counter;

    // Let inside conditionals
    declare local var.cache_key STRING;
    set var.cache_key = req.url.path;
    set req.hash = var.cache_key;
}
