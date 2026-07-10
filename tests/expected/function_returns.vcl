// Test: Function return control flow and parameter token substitution




sub vcl_recv {
    declare local var.result STRING;
    set req.http.X-Func-choose-value = "first";
    call choose;
    set var.result = req.http.X-Func-choose-Return;

    declare local var.left STRING;
    declare local var.right STRING;
    set req.http.X-Func-split-value = "left,right";
    call split;
    set var.left = req.http.X-Func-split-Return0;
    set var.right = req.http.X-Func-split-Return1;

    set req.http.X-Func-normalize-value = "left,right";
    call normalize;
    set var.result = req.http.X-Func-normalize-Return;
}

// Function: choose
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub choose {

  declare local var.value STRING;

  set var.value = req.http.X-Func-choose-value;

  declare local var.return_value STRING;

    if (var.value == "first") {
        set var.return_value = "value literal";
        set req.http.X-Func-choose-Return = var.return_value;
        return; // parameter names in strings must remain literal
    }
    if (var.value == "long") {
        set var.return_value = {"value literal"};
        set req.http.X-Func-choose-Return = var.return_value;
        return;
    }
    set req.http.value = var.value;
    set var.return_value = regsub(var.value, ",", ";");
    set req.http.X-Func-choose-Return = var.return_value;
    return;
}

// Function: split
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub split {

  declare local var.value STRING;

  set var.value = req.http.X-Func-split-value;

  declare local var.return_value0 STRING;
  declare local var.return_value1 STRING;

    set var.return_value0 = regsub(var.value, ",", ";");
    set var.return_value1 = "value literal";
    set req.http.X-Func-split-Return0 = var.return_value0;
    set req.http.X-Func-split-Return1 = var.return_value1;
    return;
}

// Function: normalize
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub normalize {

  declare local var.value STRING;

  set var.value = req.http.X-Func-normalize-value;

  declare local var.return_value STRING;

    set var.return_value = regsub(
        var.value,
        ",",
        ";"
    );
    set req.http.X-Func-normalize-Return = var.return_value;
    return;
}
