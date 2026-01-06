// Test: Advanced macro features

// Macro with operator precedence


// Nested macros


// Macro with string operations


// Macro with VCL function calls


sub vcl_recv {
    declare local var.result INTEGER;

    // Test operator precedence: should be (5 + 5) * 10 = 100
    set var.result = 5 + 5 * 10;

    // Test square with expression: should be ((2 + 3) * (2 + 3))
    set var.result = (2 + 3) * (2 + 3);

    // Test nested macro calls
    set var.result = 2 * 3 + 4 * 5;

    declare local var.str STRING;

    // Test string macros
    set var.str = "prefix_" + "name";
    set var.str = "name" + "_suffix";
    set var.str = "prefix_" + "name" + "_suffix";

    // Test VCL function macros
    set req.http.X-Normalized = std.tolower(regsub(req.http.Host, "^www\\.", ""));
    set req.http.X-Hash = digest.hash_md5(req.url + "|" + req.http.Host);
}
