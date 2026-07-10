// Test: Template expressions in #let directives

sub vcl_recv {
    declare local var.item0 STRING;
    set var.item0 = "item-0";
    set req.http.X-Item-0 = var.item0;
    declare local var.item1 STRING;
    set var.item1 = "item-1";
    set req.http.X-Item-1 = var.item1;
}
