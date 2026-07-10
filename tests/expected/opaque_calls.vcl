// Test: Macro and function-looking text in strings and comments






sub vcl_recv {
    declare local var.output STRING;

    set req.http.X-String = "suffix(req.url)";
    set req.http.X-Set = "set var.output = missing();";
    // suffix(req.url)
    // set var.output = missing();

    set req.http.X-Expanded = "input" + "-expanded";
    set req.http.X-Preserved = "value literal" + req.http.value + "input";
    set req.http.X-Incremented = "2";
    set req.http.X-First = "both"; // the next statement must remain executable
    set req.http.X-Second = "both";
    set req.http.X-Func-echo-value = "result";
    call echo;
    set var.output = req.http.X-Func-echo-Return;
}

// Function: echo
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub echo {

  declare local var.value STRING;

  set var.value = req.http.X-Func-echo-value;

  declare local var.return_value STRING;

    declare local var.copied STRING;
    set var.copied = var.value;
    set var.return_value = var.copied;
    set req.http.X-Func-echo-Return = var.return_value;
    return;
}
