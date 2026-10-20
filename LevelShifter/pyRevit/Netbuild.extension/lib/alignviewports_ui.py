"""WPF layout (XAML) for the "Align Viewports" button, and the labels of its lists.

Plain strings so they can be checked outside Revit; the button loads them with
``forms.WPFWindow(xaml, literal_string=True)``.  IronPython 2.7 + CPython 3.
"""

from align_viewports import core

COLOURS = {"OK  ": "#1B7F2A", "WARN": "#B26A00", "FAIL": "#C62828", "": "#333333"}

_NS = ('xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
       'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"')

_TYPE = '''        <CheckBox x:Name="vt_{key}" Content="{label}" Margin="0,2,14,2"/>'''

_WINDOW = '''<Window {ns}
        Title="Align Viewports by Netbuild" Width="1040" Height="900" MinWidth="860" MinHeight="640"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" FontSize="12" ShowInTaskbar="False">
  <DockPanel Margin="10">
    <StackPanel DockPanel.Dock="Top">
      <TextBlock x:Name="model_tb" FontWeight="Bold" FontSize="13"/>
      <TextBlock Foreground="#555555" Margin="0,2,0,0" TextWrapping="Wrap"
                 Text="Each target viewport goes to the place of the reference viewport in the same slot (top -> bottom on the sheet), by its projection origin, so the plans and their grids line up. View titles take the reference's position and line length."/>
    </StackPanel>
    <Grid DockPanel.Dock="Top" Margin="0,8,0,0" Height="300">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <DockPanel Grid.Column="0" Margin="0,0,6,0">
        <GroupBox DockPanel.Dock="Top" Header="1. Reference sheet -- its viewports are where you want them">
          <StackPanel Margin="4">
            <ComboBox x:Name="ref_cb"/>
            <TextBlock x:Name="ref_info_tb" Foreground="#555555" Margin="0,4,0,0" TextWrapping="Wrap"/>
          </StackPanel>
        </GroupBox>
        <GroupBox Header="2. Viewports to align" Margin="0,6,0,0">
          <StackPanel Margin="4">
            <WrapPanel>
{types}
            </WrapPanel>
            <CheckBox x:Name="titles_cb" Margin="0,8,0,0"
                      Content="Align the view titles too (position and line length)"/>
            <TextBlock Foreground="#555555" Margin="0,4,0,0" TextWrapping="Wrap"
                       Text="Legends, schedules and unticked kinds of view stay where they are."/>
          </StackPanel>
        </GroupBox>
      </DockPanel>
      <GroupBox Grid.Column="1" Header="3. Target sheets">
        <DockPanel Margin="4">
          <WrapPanel DockPanel.Dock="Top">
            <TextBlock Text="Numbers" VerticalAlignment="Center" Margin="0,0,6,0"/>
            <TextBox x:Name="from_tb" Width="70"/>
            <TextBlock Text="to" VerticalAlignment="Center" Margin="6,0,6,0"/>
            <TextBox x:Name="to_tb" Width="70"/>
            <TextBlock Text="and also" VerticalAlignment="Center" Margin="10,0,6,0"/>
            <TextBox x:Name="extra_tb" Width="130" ToolTip="Other sheet numbers, e.g. 10B01, 10B02"/>
          </WrapPanel>
          <WrapPanel DockPanel.Dock="Top" Margin="0,6,0,0">
            <Button x:Name="range_btn" Content="Select these" Padding="8,1" Margin="0,0,6,0"/>
            <Button x:Name="all_btn" Content="All sheets" Padding="8,1" Margin="0,0,6,0"/>
            <Button x:Name="none_btn" Content="None" Padding="8,1" Margin="0,0,10,0"/>
            <TextBlock x:Name="count_tb" Foreground="#555555" VerticalAlignment="Center"/>
          </WrapPanel>
          <ListBox x:Name="tgt_lb" SelectionMode="Extended" Margin="0,6,0,0"/>
        </DockPanel>
      </GroupBox>
    </Grid>
    <TextBlock DockPanel.Dock="Top" Foreground="#555555" Margin="0,4,0,0" TextWrapping="Wrap"
               Text="Ctrl+Click / Shift+Click picks sheets by hand. A sheet with more viewports than the reference is skipped; one with fewer is aligned to the reference's top slots."/>
    <WrapPanel DockPanel.Dock="Top" Margin="0,8,0,0">
      <Button x:Name="check_btn" Content="Check (plan only)" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="trial_btn" Content="Trial run (rolls back)" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="apply_btn" Content="Apply" Padding="10,3" Margin="0,0,20,0" FontWeight="Bold"/>
      <Button x:Name="images_btn" Content="Export check images" Padding="10,3" Margin="0,0,6,0"
              ToolTip="PNG of the reference and up to 3 picked sheets, to compare the view titles"/>
      <Button x:Name="logs_btn" Content="Open logs folder" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="about_btn" Content="About" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="licence_btn" Content="Licence" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="close_btn" Content="Close" Padding="10,3"/>
    </WrapPanel>
    <DockPanel DockPanel.Dock="Top" Margin="0,8,0,0">
      <TextBlock DockPanel.Dock="Left" Text="Time-saved log (CSV)" VerticalAlignment="Center" Margin="0,0,8,0"/>
      <TextBox x:Name="minutes_tb" DockPanel.Dock="Right" Width="50"
               ToolTip="Minutes the same work takes by hand, per viewport"/>
      <TextBlock DockPanel.Dock="Right" Text="manual minutes per viewport" VerticalAlignment="Center"
                 Margin="10,0,6,0"/>
      <Button x:Name="log_btn" DockPanel.Dock="Right" Content="Pick..." Padding="8,1" Margin="6,0,0,0"/>
      <TextBox x:Name="log_tb" ToolTip="After Apply, one row is added here. Leave blank for no row."/>
    </DockPanel>
    <TextBlock x:Name="status_tb" DockPanel.Dock="Top" Foreground="#555555" Margin="0,6,0,0" TextWrapping="Wrap"/>
    <ListBox x:Name="report_lb" Margin="0,6,0,0" FontFamily="Consolas" FontSize="11"
             ScrollViewer.HorizontalScrollBarVisibility="Auto"/>
  </DockPanel>
</Window>'''


def window_xaml():
    types = "\n".join(_TYPE.format(key=k, label=l) for k, l in core.VIEW_TYPES)
    return _WINDOW.format(ns=_NS, types=types)


def sheet_label(number, name):
    """'10023 - LEVEL 23 GA PLAN'."""
    return u"%s - %s" % (number, name)


def ref_info(slots):
    """'2 viewport slots, top -> bottom: L23 PLAN; L23 KEY PLAN' for the reference."""
    if not slots:
        return u"No viewport of the ticked kinds on this sheet."
    return u"%d viewport slot%s, top -> bottom: %s" % (len(slots), "" if len(slots) == 1 else "s",
                                                        u"; ".join(slots))


def report_lines(checks, lines):
    """[(colour, text)] for the report list: the checks (coloured by result), then the detail lines."""
    out = [(COLOURS[c.mark], str(c)) for c in checks]
    return out + [(COLOURS[""], l) for l in lines]
