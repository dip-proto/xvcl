// Test: Multi-line function calls



sub vcl_recv {
    declare local var.result STRING;

    // Multi-line function call
    set req.http.X-Func-process-input = req.http.Host;
    set req.http.X-Func-process-prefix = "prefix_";
    set req.http.X-Func-process-suffix = "_suffix";
    call process;
    set var.result = req.http.X-Func-process-Return;
    unset req.http.X-Func-process-Return;

    // Another multi-line call with more complex args
    set req.http.X-Func-process-input = "input_string";
    set req.http.X-Func-process-prefix = "<<";
    set req.http.X-Func-process-suffix = ">>";
    call process;
    set var.result = req.http.X-Func-process-Return;
    unset req.http.X-Func-process-Return;

    // Multi-line calls after a multi-line #for list
    set req.http.X-Func-process-input = req.http.Host;
    set req.http.X-Func-process-prefix = "";
    set req.http.X-Func-process-suffix = "_a";
    call process;
    set var.result = req.http.X-Func-process-Return;
    unset req.http.X-Func-process-Return;
    set req.http.X-Func-process-input = req.http.Host;
    set req.http.X-Func-process-prefix = "";
    set req.http.X-Func-process-suffix = "_b";
    call process;
    set var.result = req.http.X-Func-process-Return;
    unset req.http.X-Func-process-Return;
    set req.http.X-Func-size_class-choice = req.http.X-Size;
    call size_class;
    set var.result = req.http.X-Func-size_class-Return;
    unset req.http.X-Func-size_class-Return;
    set req.http.X-Func-wrap-input = var.result;
    call wrap;
    set var.result = req.http.X-Func-wrap-Return;
    unset req.http.X-Func-wrap-Return;
}

// Function: process
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub process {

  declare local var.input STRING;
  declare local var.prefix STRING;
  declare local var.suffix STRING;

  set var.input = req.http.X-Func-process-input;
  unset req.http.X-Func-process-input;
  set var.prefix = req.http.X-Func-process-prefix;
  unset req.http.X-Func-process-prefix;
  set var.suffix = req.http.X-Func-process-suffix;
  unset req.http.X-Func-process-suffix;

  declare local var.return_value STRING;

    declare local var.result STRING;
    set var.result = var.prefix + var.input + var.suffix;
    set var.return_value = var.result;
    set req.http.X-Func-process-Return = var.return_value;
    return;
}

// Function: size_class
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub size_class {

  declare local var.choice STRING;

  set var.choice = req.http.X-Func-size_class-choice;
  unset req.http.X-Func-size_class-choice;

  declare local var.return_value STRING;

    if (var.choice == "small") {
        set var.return_value = "small";
        set req.http.X-Func-size_class-Return = var.return_value;
        return;
    }
    if (var.choice == "large") {
        set var.return_value = "large";
        set req.http.X-Func-size_class-Return = var.return_value;
        return;
    }
    set var.return_value = "none";
    set req.http.X-Func-size_class-Return = var.return_value;
    return;
}

// Function: wrap
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub wrap {

  declare local var.input STRING;

  set var.input = req.http.X-Func-wrap-input;
  unset req.http.X-Func-wrap-input;

  declare local var.return_value STRING;

    declare local var.wrapped STRING;
    set req.http.X-Func-process-input = var.input;
    set req.http.X-Func-process-prefix = "<";
    set req.http.X-Func-process-suffix = ">";
    call process;
    set var.wrapped = req.http.X-Func-process-Return;
    unset req.http.X-Func-process-Return;
    set var.return_value = var.wrapped;
    set req.http.X-Func-wrap-Return = var.return_value;
    return;
}
