// Test: Fastly concatenates repeated lifecycle subroutines

sub vcl_recv {
    set req.http.X-First = "1";
}

sub vcl_recv {
    set req.http.X-Second = "1";
}
