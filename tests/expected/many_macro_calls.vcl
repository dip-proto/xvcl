// Test: More than ten independent macro calls on one line


sub vcl_recv {
    declare local var.output STRING;
    set var.output = "1" "2" "3" "4" "5" "6" "7" "8" "9" "10" "11";
}
