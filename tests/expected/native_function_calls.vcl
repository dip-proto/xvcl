// Test: Native VCL functions and builtins pass through unchanged

sub native_echo(STRING var.value) STRING {
    return var.value;
}

sub vcl_recv {
    declare local var.output STRING;
    set var.output = native_echo("result");

    declare local var.random BOOL;
    set var.random = randombool(1, 2);
}
