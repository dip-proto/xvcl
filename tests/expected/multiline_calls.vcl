// Test: Multi-line function calls

sub vcl_recv {
    declare local var.result STRING;

    // Multi-line function call
    set req.http.X-Func-process-input = req.http.Host;
    set req.http.X-Func-process-prefix = "prefix_";
    set req.http.X-Func-process-suffix = "_suffix";
    call process;
    set var.result = req.http.X-Func-process-Return;

    // Another multi-line call with more complex args
    set req.http.X-Func-process-input = "input_string";
    set req.http.X-Func-process-prefix = "<<";
    set req.http.X-Func-process-suffix = ">>";
    call process;
    set var.result = req.http.X-Func-process-Return;
}

// Function: process
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub process {

  declare local var.input STRING;
  declare local var.prefix STRING;
  declare local var.suffix STRING;

  set var.input = req.http.X-Func-process-input;
  set var.prefix = req.http.X-Func-process-prefix;
  set var.suffix = req.http.X-Func-process-suffix;

  declare local var.return_value STRING;

    declare local var.result STRING;
    set var.result = var.prefix + var.input + var.suffix;
    set var.return_value = var.result;

  set req.http.X-Func-process-Return = var.return_value;
}
