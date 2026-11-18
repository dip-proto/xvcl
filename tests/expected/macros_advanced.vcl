// Test: Advanced macro features

// Boolean expression macros



// Macro with string operations


// Macro with VCL function calls


// Parameters are replaced all at once, and only once






sub vcl_recv {
    // Test nested boolean macro calls
    if (req.method == "GET" && req.url.path ~ "\\.(?:css|js)$") {
        set req.http.X-Asset-Get = "1";
    }

    declare local var.str STRING;

    // Test string macros
    set var.str = "prefix_" + "name";
    set var.str = "name" + "_suffix";
    set var.str = "prefix_" + "name" + "_suffix";

    // Test VCL function macros
    set req.http.X-Normalized = std.tolower(regsub(req.http.Host, "^www\\.", ""));
    set req.http.X-Hash = digest.hash_md5(req.url + "|" + req.http.Host);

    // An argument named like another parameter isn't replaced again
    set req.http.X-Pair = "k1=v1";
    set req.http.X-Both = right && req.http.Host;

    declare local var.n INTEGER;
    set var.n = 21;
    set var.n = 3;
    set var.n = 3600;
    set var.n = 8;
}
