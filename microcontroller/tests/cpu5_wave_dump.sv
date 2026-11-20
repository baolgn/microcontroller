/* dump every traced signal of a bound fixture for waveform figures; +wave=<file> selects the output. */
module cpu5_wave_dump;
  string path;

  /* open the dump before the first clock edge so reset and the first offers are visible. */
  initial begin
    if (!$value$plusargs("wave=%s", path)) path = "cpu5.vcd";
    $dumpfile(path);
    $dumpvars;
  end
endmodule
